import 'package:flutter/material.dart';

import 'app.dart';
import 'core/api_client.dart';
import 'core/settings.dart';
import 'voice/voice_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = await AppSettings.load();
  final api = ApiClient(baseUrl: () => settings.baseUrl);
  runApp(RimaApp(settings: settings, api: api, voice: RealVoiceService()));
}
