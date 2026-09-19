import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rima_mobile/core/api_client.dart';
import 'package:rima_mobile/core/settings.dart';
import 'package:rima_mobile/voice/voice_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

ApiClient fakeApi(Future<http.Response> Function(http.Request) handler, {String base = 'http://test'}) =>
    ApiClient(baseUrl: () => base, client: MockClient(handler));

http.Response jsonResponse(Object? body, {int status = 200}) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json; charset=utf-8'});

Future<AppSettings> makeSettings([Map<String, Object> initial = const {}]) async {
  SharedPreferences.setMockInitialValues(initial);
  return AppSettings(await SharedPreferences.getInstance());
}

/// Stands in for the device's speech engines so tests can play the part of the
/// user talking and of Rima speaking.
class FakeVoiceService implements VoiceService {
  bool speechAvailable = true;
  String? startedLanguage;
  int startListeningCalls = 0;
  int stopSpeakingCalls = 0;
  final List<String> spoken = [];

  /// When set, speak() stays "in progress" until this completes.
  Completer<void>? speakGate;

  bool _listening = false;
  SpeechResultCallback? _onResult;
  void Function(String)? _onError;
  VoidCallback? _onDone;

  @override
  bool get isListening => _listening;

  @override
  Future<bool> initSpeech() async => speechAvailable;

  @override
  Future<void> startListening({
    required String language,
    required SpeechResultCallback onResult,
    required void Function(String message) onError,
    VoidCallback? onDone,
  }) async {
    startListeningCalls++;
    startedLanguage = language;
    _listening = true;
    _onResult = onResult;
    _onError = onError;
    _onDone = onDone;
  }

  @override
  Future<void> stopListening() async {
    // a real recogniser delivers a final result, then reports "done"
    if (_listening && _pendingText.isNotEmpty) hear(_pendingText, isFinal: true);
    finish();
  }

  String _pendingText = '';

  // ---- test controls ----------------------------------------------------

  void hear(String text, {bool isFinal = false}) {
    _pendingText = text;
    _onResult?.call(text, isFinal);
    if (isFinal) _pendingText = '';
  }

  void fail(String message) {
    _listening = false;
    _onError?.call(message);
  }

  void finish() {
    _listening = false;
    _onDone?.call();
  }

  // ---- speaking ---------------------------------------------------------

  @override
  Future<void> speak(String text) async {
    spoken.add(text);
    if (speakGate != null) await speakGate!.future;
  }

  @override
  Future<void> stopSpeaking() async {
    stopSpeakingCalls++;
  }

  @override
  Future<bool> isLanguageAvailable(String bcp47) async => true;

  @override
  void dispose() {}
}
