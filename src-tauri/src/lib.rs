mod core;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(core::Core::default())
        .invoke_handler(tauri::generate_handler![core::core, core::logs_dir])
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            // Never leave the story or image model running (and holding memory) after quitting.
            if let tauri::RunEvent::Exit = event {
                app.state::<core::Core>().shutdown(app);
            }
        });
}
