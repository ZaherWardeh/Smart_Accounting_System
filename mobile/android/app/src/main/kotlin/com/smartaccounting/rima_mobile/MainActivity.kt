package com.smartaccounting.rima_mobile

import android.content.ActivityNotFoundException
import android.content.Intent
import android.provider.Settings
import android.speech.tts.TextToSpeech
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/// Deep-links into the phone's own voice settings, so a user missing the Arabic
/// speech pack doesn't have to hunt for it themselves. No plugin dependency -
/// just two documented system Intents, tried directly and caught if the phone
/// (or its current default assistant/TTS engine) doesn't have that screen.
class MainActivity : FlutterActivity() {
    private val CHANNEL = "rima/system_settings"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                // Speech-to-text: "Voice input" system settings, where offline
                // recognition language packs (e.g. Arabic) are downloaded.
                "openVoiceInputSettings" -> result.success(tryStart(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)))
                // Text-to-speech: the current engine's own "install voice data" screen.
                "openTtsInstallSettings" -> result.success(tryStart(Intent(TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA)))
                else -> result.notImplemented()
            }
        }
    }

    private fun tryStart(intent: Intent): Boolean {
        return try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(intent)
            true
        } catch (e: ActivityNotFoundException) {
            false
        }
    }
}
