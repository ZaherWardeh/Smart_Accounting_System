# Rima Mobile (Flutter)

A phone version of the Smart Accounting website: dashboard, chart of accounts (tree), journal entries,
reports, and **Rima** — who you can talk to, and who talks back.

It is a thin client over the existing REST API. Speech-to-text and text-to-speech run on the phone itself.

## Screens

| Tab | What it does |
| --- | --- |
| الرئيسية | Income / expense / balance summary, shortcuts. Pull to refresh. |
| الحسابات | Chart of accounts as a collapsible tree in code order; add / edit / delete (409 from the server is shown as a message). |
| القيود | Journal entries, newest first; add / edit with live balance check (save is disabled until debits = credits); delete; a 📎 on an entry with a saved document opens a zoomable viewer. |
| التقارير | Statement of account (optional date range; a master account rolls up its children) and balance for several accounts. |
| ريما | Chat. Tap the mic and speak, or attach a document photo — Rima answers in text **and out loud**. Can also record a journal entry or create a new account, see below. |
| ⚙ (top bar) | Server URL (+ connection test), auto-speak on/off, speech language, "try Rima's voice". |

The UI is Arabic / RTL. Conversation memory is kept per install (`conversation_id`) until you press "محادثة جديدة".

## Recording a transaction / adding an account through Rima

Ask Rima to record an entry ("سجل قيد إيجار 100 من الصندوق") or add an account she doesn't have. The
**server** owns the rules — the app is just the UI for them (see the root [README.md](../README.md#recording-a-transaction-or-a-new-account-through-rima)
for how the server enforces it):

- Missing fields (debit account, then credit account, then amount — or name, parent, closing type, then a
  suggested code for a new account) are asked **one at a time**, with numbered suggestions.
- Before anything saves, Rima reads it back and needs an actual **confirm**.
- If you go quiet for about a minute with something unsaved, a card appears (and Rima says it) offering
  **Confirm / Modify / Abort** — it also reappears when you reopen the chat, and "محادثة جديدة" warns you
  first if something is still unsaved.
- Tap 📎 in the chat to attach a bill/receipt photo from the gallery. Rima reads it (vendor, date, total,
  line items) and uses it as her first source for account/amount suggestions — the amount is always a
  *proposal* you confirm, never applied silently. The image is saved with the entry once you confirm.

## Voice

- **Input:** `speech_to_text` (the phone's own recogniser). Language follows the setting (Arabic by default;
  falls back to English). Partial results appear live in the text box; a pause ends the utterance and sends it.
- **Output:** `flutter_tts`. Arabic replies use an Arabic voice, everything else English. Markdown is stripped
  before speaking; long replies are read in chunks. Tapping the mic while Rima talks interrupts her.
- Arabic recognition/voice needs the language pack on the phone (Android: Google app → Voice, and *Settings →
  System → Languages → Text-to-speech*). If it's missing the app tells you instead of failing silently.

## Run it

You need the Flutter SDK (developed on 3.24) and a running backend.

```bash
cd mobile
flutter pub get
flutter run
```

**Server URL** — set it in ⚙ inside the app (saved on the phone):

| Where the app runs | URL |
| --- | --- |
| Android emulator, backend on your PC | `http://10.0.2.2:8000` (the default) |
| Real phone, backend on the server | `http://<the-static-ip>` (Nginx, port 80) |
| Real phone, backend behind HTTPS | `https://your.domain` |

**API only (no website):** start the backend with `SERVE_WEB=0` (e.g. `SERVE_WEB=0 uvicorn main:app --host 127.0.0.1 --port 8000`)
and only the REST API is served - `/`, `/accounts` pages and `/static` return 404. Handy behind a temporary tunnel
(`cloudflared tunnel --url http://127.0.0.1:8000`): paste the resulting `https://….trycloudflare.com` link into the app.
There is no login, so treat the link as a secret and stop the tunnel when you're done.

> The server is reached by plain IP over **HTTP**, so the app allows cleartext traffic (Android
> `usesCleartextTraffic`, iOS ATS exception). Once you put Nginx + Certbot (HTTPS) in front, use the `https://`
> URL and remove those two allowances. Note that voice questions travel to the server as text, and without
> HTTPS they are readable on the network.

## Test

```bash
flutter analyze
flutter test        # 140 tests: API client, account tree, speech text, chat/voice flow, drafts/attachments, widget smoke tests
```

Voice is tested through a fake `VoiceService`; the real microphone / TTS engine can only be checked on a device.

## Build

```bash
flutter build apk --release      # build/app/outputs/flutter-apk/app-release.apk
```

(For the Play Store you need your own signing key — the project currently signs release builds with the debug key.)

## Toolchain notes (Flutter 3.24)

Newer plugin releases need a newer Flutter/Kotlin than 3.24 ships, so a few versions are pinned on purpose:
`speech_to_text 7.0.0`, `flutter_tts 4.0.2`, `shared_preferences_android 2.3.4` and
`flutter_plugin_android_lifecycle 2.0.14` (all `dependency_overrides` entries — the lifecycle one is pulled in
transitively by `image_picker`, and newer releases need `compileSdk 35`, whose resource table this old AGP's
`aapt2` can't parse: `Android resource linking failed ... LoadedArsc.cpp ... entry offsets overlap`), and the
Kotlin Gradle plugin is 1.9.24 (`android/settings.gradle`). When you upgrade Flutter, these can be un-pinned.
Verified: `flutter build apk --release` succeeds; the merged manifest has `RECORD_AUDIO` and the speech/TTS
`<queries>`.

## Layout

`lib/core` (API client, settings, formatting) · `lib/models` (incl. `PendingDraft`, `RimaAttachment`) ·
`lib/voice` (STT/TTS behind `VoiceService`) ·
`lib/chat` (`ChatController`, `AttachmentPicker` behind an interface so tests don't need a real gallery) ·
`lib/screens` (incl. `document_viewer.dart`) · `lib/widgets`.

Picking a gallery image needs `NSPhotoLibraryUsageDescription` on iOS (already in `Info.plist`); Android
needs no extra permission for the system photo picker `image_picker` uses.
