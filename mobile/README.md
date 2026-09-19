# Rima Mobile (Flutter)

A phone version of the Smart Accounting website: dashboard, chart of accounts (tree), journal entries,
reports, and **Rima** — who you can talk to, and who talks back.

It is a thin client over the existing REST API. **The backend is unchanged** — no new endpoints, no extra
API cost: speech-to-text and text-to-speech run on the phone itself.

## Screens

| Tab | What it does |
| --- | --- |
| الرئيسية | Income / expense / balance summary, shortcuts. Pull to refresh. |
| الحسابات | Chart of accounts as a collapsible tree in code order; add / edit / delete (409 from the server is shown as a message). |
| القيود | Journal entries, newest first; add / edit with live balance check (save is disabled until debits = credits); delete. |
| التقارير | Statement of account (optional date range; a master account rolls up its children) and balance for several accounts. |
| ريما | Chat. Tap the mic and speak; Rima answers in text **and out loud**. |
| ⚙ (top bar) | Server URL (+ connection test), auto-speak on/off, speech language, "try Rima's voice". |

The UI is Arabic / RTL. Conversation memory is kept per install (`conversation_id`) until you press "محادثة جديدة".

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

> The server is reached by plain IP over **HTTP**, so the app allows cleartext traffic (Android
> `usesCleartextTraffic`, iOS ATS exception). Once you put Nginx + Certbot (HTTPS) in front, use the `https://`
> URL and remove those two allowances. Note that voice questions travel to the server as text, and without
> HTTPS they are readable on the network.

## Test

```bash
flutter analyze
flutter test        # 79 tests: API client, account tree, speech text, chat/voice flow, widget smoke tests
```

Voice is tested through a fake `VoiceService`; the real microphone / TTS engine can only be checked on a device.

## Build

```bash
flutter build apk --release      # build/app/outputs/flutter-apk/app-release.apk
```

(For the Play Store you need your own signing key — the project currently signs release builds with the debug key.)

## Toolchain notes (Flutter 3.24)

Newer plugin releases need a newer Flutter/Kotlin than 3.24 ships, so a few versions are pinned on purpose:
`speech_to_text 7.0.0`, `flutter_tts 4.0.2`, `shared_preferences_android 2.3.4` (a `dependency_overrides` entry),
and the Kotlin Gradle plugin is 1.9.24 (`android/settings.gradle`). When you upgrade Flutter, these can be
un-pinned. Verified: `flutter build apk --debug` succeeds; the merged manifest has `RECORD_AUDIO` and the
speech/TTS `<queries>`.

## Layout

`lib/core` (API client, settings, formatting) · `lib/models` · `lib/voice` (STT/TTS behind `VoiceService`) ·
`lib/chat` (`ChatController`) · `lib/screens` · `lib/widgets`.
