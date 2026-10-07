"""Entry point for the bundled Stickman Studio core (built into one executable by scripts/build-core.sh)."""

import truststore

# The bundled Python's OpenSSL looks for CA certificates at a path that doesn't exist on macOS, so
# every HTTPS request (model downloads, Cloudflare) failed with CERTIFICATE_VERIFY_FAILED. Verify
# against the macOS keychain instead, which also picks up any certificates an organisation installs.
truststore.inject_into_ssl()

from stickman_core.ipc import main  # noqa: E402

if __name__ == "__main__":
    main()
