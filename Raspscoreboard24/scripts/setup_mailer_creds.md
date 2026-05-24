# Shutdown mailer -- Pi-side credential setup

The `shutdown_mailer.py` script runs as `ExecStopPost=` on
`scoreboard24.service` and sends one digest email per service stop. SMTP
credentials (sender, recipient, Gmail app password) are encrypted at rest
via `systemd-creds` so the repo and the Pi's disk never carry plaintext.

This setup is **one-time per Pi**. The plaintext JSON only exists on a
tmpfs (`/run/`) for the duration of the encryption step; it is shredded
before the credstore file is written to flash.

## Prerequisites

- A Gmail account with **2-Step Verification** enabled.
- An **App Password** generated for that account
  (Google Account -> Security -> 2-Step Verification -> App Passwords ->
  name it `scoreboard24-pi`). The 16-character output is what goes into
  `app_password` below; spaces are optional.

## Steps

```bash
# 1. Write plaintext temporarily on tmpfs (never lands on flash).
sudo install -d -m 0700 /run/mailer-setup
sudoedit /run/mailer-setup/mailer_creds.json
# Paste the JSON from mailer_creds.example.json, fill in real values, save.

# 2. Encrypt to the system credstore.
sudo install -d -m 0755 /etc/credstore.encrypted
sudo systemd-creds encrypt --name=scoreboard24-mailer \
    /run/mailer-setup/mailer_creds.json \
    /etc/credstore.encrypted/scoreboard24-mailer.cred
sudo chmod 0640 /etc/credstore.encrypted/scoreboard24-mailer.cred

# 3. Shred plaintext, drop the tmpfs dir.
sudo shred -u /run/mailer-setup/mailer_creds.json
sudo rm -rf /run/mailer-setup

# 4. Confirm decrypt works (prints the first 40 bytes of the JSON).
sudo systemd-creds decrypt /etc/credstore.encrypted/scoreboard24-mailer.cred - \
    | head -c 40 ; echo

# 5. Reload + restart so the LoadCredentialEncrypted= directive takes effect.
sudo systemctl daemon-reload
sudo systemctl restart scoreboard24.service
```

The credential name passed to `--name=` (here `scoreboard24-mailer`) must
match the credential ID in `scoreboard24.service`'s
`LoadCredentialEncrypted=` directive, otherwise systemd will refuse to
decrypt at unit start.

## Dry-run verification

Send a test email immediately without waiting for a real service stop:

```bash
sudo systemd-run --pty --wait --unit=mailer-test \
  --property=LoadCredentialEncrypted=scoreboard24-mailer:/etc/credstore.encrypted/scoreboard24-mailer.cred \
  /usr/bin/python3 /home/tenumen/scoreboard24/scripts/shutdown_mailer.py \
    --since=-1h --force-send
```

`--force-send` bypasses the "nothing to report -> skip" shortcut.

## Security notes

- The encrypted credstore file is bound to **this Pi's host key**
  (`/var/lib/systemd/credential.secret`, mode 0600 root, auto-created on
  first encrypt). Copying the `.cred` to another machine will fail to
  decrypt.
- The Pi 3B has no TPM, so the host key lives on the SD card. A root
  compromise of the Pi defeats this. The threat model is "repo +
  fileshare + offline-disk reads remain safe" -- not "rooted Pi remains
  safe".
- If you regenerate the Gmail app password, repeat steps 1-5; the
  filename does not change.
