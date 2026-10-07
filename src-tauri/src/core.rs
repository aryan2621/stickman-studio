//! Talks to the Python core (`core/`), which runs as a Tauri sidecar and does the actual work:
//! planning, voice, drawing and rendering. Protocol: one JSON object per line on stdin/stdout.
//! Requests carry an `id` and get a reply with the same `id`; messages with an `event` field are
//! pushed by the core (job progress, downloads) and forwarded to the UI as `core-event`.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;

type Reply = Result<Value, String>;

#[derive(Default)]
pub struct Core {
    child: Mutex<Option<CommandChild>>,
    pending: Mutex<HashMap<u64, oneshot::Sender<Reply>>>,
    next_id: AtomicU64,
}

impl Core {
    pub async fn call(&self, app: &AppHandle, method: &str, params: Value, timeout: Option<Duration>) -> Reply {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed) + 1;
        let (tx, rx) = oneshot::channel();
        self.pending.lock().unwrap().insert(id, tx);

        let mut line = serde_json::to_vec(&json!({ "id": id, "method": method, "params": params })).map_err(|e| e.to_string())?;
        line.push(b'\n');
        if let Err(error) = self.write(app, line) {
            self.pending.lock().unwrap().remove(&id);
            return Err(error);
        }

        let reply = match timeout {
            Some(limit) => match tokio::time::timeout(limit, rx).await {
                Ok(result) => result,
                Err(_) => {
                    self.pending.lock().unwrap().remove(&id);
                    return Err(format!("The engine did not answer `{method}` in time"));
                }
            },
            None => rx.await,
        };
        reply.unwrap_or_else(|_| Err("The engine stopped unexpectedly".into()))
    }

    fn write(&self, app: &AppHandle, line: Vec<u8>) -> Result<(), String> {
        let mut child = self.child.lock().unwrap();
        if child.is_none() {
            *child = Some(spawn(app)?);
        }
        child.as_mut().unwrap().write(&line).map_err(|e| format!("Could not reach the engine: {e}"))
    }

    fn resolve(&self, message: &Value) {
        let Some(id) = message.get("id").and_then(Value::as_u64) else { return };
        let Some(tx) = self.pending.lock().unwrap().remove(&id) else { return };
        let reply = if message.get("ok").and_then(Value::as_bool) == Some(true) {
            Ok(message.get("result").cloned().unwrap_or(Value::Null))
        } else {
            Err(message.get("error").and_then(Value::as_str).unwrap_or("Unknown engine error").to_string())
        };
        let _ = tx.send(reply);
    }

    fn terminated(&self) {
        *self.child.lock().unwrap() = None;
        for (_, tx) in self.pending.lock().unwrap().drain() {
            let _ = tx.send(Err("The engine stopped unexpectedly".into()));
        }
    }

    /// Asks the core to stop its engines (they hold gigabytes of memory), then ends it.
    pub fn shutdown(&self, app: &AppHandle) {
        if self.child.lock().unwrap().is_none() {
            return;
        }
        let _ = tauri::async_runtime::block_on(self.call(app, "shutdown", json!({}), Some(Duration::from_secs(5))));
        if let Some(child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

fn spawn(app: &AppHandle) -> Result<CommandChild, String> {
    let paths = app.path();
    let data = paths.app_data_dir().map_err(|e| e.to_string())?;
    let logs = paths.app_log_dir().map_err(|e| e.to_string())?;
    // The native servers are sidecars too, next to the app's own executable.
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let bin = exe.parent().ok_or("No app folder")?.to_path_buf();

    let (mut events, child) = app
        .shell()
        .sidecar("stickman-core")
        .map_err(|e| format!("Could not start the engine: {e}"))?
        .env("STICKMAN_DATA_DIR", data)
        .env("STICKMAN_LOG_DIR", logs)
        .env("STICKMAN_BIN_DIR", bin)
        .spawn()
        .map_err(|e| format!("Could not start the engine: {e}"))?;

    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut buffer = Vec::new();
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(chunk) => {
                    buffer.extend_from_slice(&chunk);
                    // Lines may arrive split or batched; only parse complete ones.
                    while let Some(end) = buffer.iter().position(|&b| b == b'\n') {
                        let line: Vec<u8> = buffer.drain(..=end).collect();
                        handle_line(&app, &line);
                    }
                    if !buffer.is_empty() && serde_json::from_slice::<Value>(&buffer).is_ok() {
                        let line = std::mem::take(&mut buffer);
                        handle_line(&app, &line);
                    }
                }
                CommandEvent::Stderr(line) => eprintln!("[core] {}", String::from_utf8_lossy(&line).trim_end()),
                CommandEvent::Terminated(status) => {
                    eprintln!("[core] exited: {status:?}");
                    app.state::<Core>().terminated();
                    let _ = app.emit("core-event", json!({ "event": "exited", "data": null }));
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(child)
}

fn handle_line(app: &AppHandle, line: &[u8]) {
    let text = String::from_utf8_lossy(line);
    let text = text.trim();
    if text.is_empty() {
        return;
    }
    let Ok(message) = serde_json::from_str::<Value>(text) else {
        eprintln!("[core] unexpected output: {text}");
        return;
    };
    if message.get("id").is_some() {
        app.state::<Core>().resolve(&message);
    } else if message.get("event").is_some() {
        let _ = app.emit("core-event", message);
    }
}

/// Every UI request goes through here: `method` names a core method (see core/stickman_core/ipc.py).
#[tauri::command]
pub async fn core(app: AppHandle, core: State<'_, Core>, method: String, params: Option<Value>) -> Result<Value, String> {
    core.call(&app, &method, params.unwrap_or(Value::Null), None).await
}

/// The folder with the engine logs, for "Show logs".
#[tauri::command]
pub fn logs_dir(app: AppHandle) -> Result<String, String> {
    let dir = app.path().app_log_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.to_string_lossy().into_owned())
}
