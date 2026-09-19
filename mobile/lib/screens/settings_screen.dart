import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/settings.dart';
import '../voice/voice_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _url;
  String? _status;
  bool _statusOk = false;
  bool _testing = false;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: context.read<AppSettings>().baseUrl);
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    await context.read<AppSettings>().setBaseUrl(normalizeBaseUrl(_url.text));
    if (mounted) _url.text = context.read<AppSettings>().baseUrl;
  }

  Future<void> _testConnection() async {
    await _save();
    if (!mounted) return;
    setState(() {
      _testing = true;
      _status = null;
    });
    try {
      final h = await context.read<ApiClient>().health();
      final llm = h['llm_connected'] == true;
      if (mounted) {
        setState(() {
          _statusOk = true;
          _status = llm ? 'الاتصال ناجح، وريما جاهزة ✓' : 'الاتصال ناجح، لكن مفتاح Gemini غير مضبوط على الخادم';
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _statusOk = false;
          _status = e.message;
        });
      }
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  Future<void> _testVoice() async {
    final voice = context.read<VoiceService>();
    final messenger = ScaffoldMessenger.of(context);
    final ok = await voice.isLanguageAvailable('ar-SA');
    if (!ok) {
      messenger.showSnackBar(const SnackBar(
        content: Text('صوت عربي غير مثبّت على الجهاز. ثبّته من إعدادات النظام ← تحويل النص إلى كلام'),
      ));
    }
    await voice.speak('مرحباً، أنا ريما، محاسبتك الذكية. كيف فيني ساعدك؟');
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<AppSettings>();
    return Scaffold(
      appBar: AppBar(title: const Text('الإعدادات')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('الخادم', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          TextField(
            controller: _url,
            keyboardType: TextInputType.url,
            textDirection: TextDirection.ltr,
            decoration: const InputDecoration(
              labelText: 'عنوان الخادم',
              hintText: 'http://192.168.1.10:8000',
              helperText: 'IP الخادم الثابت (مع البورت إذا لزم). للمحاكي: http://10.0.2.2:8000',
              helperMaxLines: 2,
              border: OutlineInputBorder(),
            ),
            onSubmitted: (_) => _save(),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              FilledButton.icon(
                onPressed: _testing ? null : _testConnection,
                icon: _testing
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.wifi_tethering),
                label: const Text('حفظ واختبار الاتصال'),
              ),
            ],
          ),
          if (_status != null) ...[
            const SizedBox(height: 10),
            Text(
              _status!,
              style: TextStyle(color: _statusOk ? Colors.green.shade700 : Theme.of(context).colorScheme.error),
            ),
          ],
          const Divider(height: 36),
          Text('الصوت', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('ريما تقرأ الردود بصوتها'),
            value: settings.autoSpeak,
            onChanged: settings.setAutoSpeak,
          ),
          const SizedBox(height: 6),
          const Text('لغة التعرف على صوتك'),
          const SizedBox(height: 6),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'ar', label: Text('العربية')),
              ButtonSegment(value: 'en', label: Text('English')),
            ],
            selected: {settings.speechLang},
            onSelectionChanged: (s) => settings.setSpeechLang(s.first),
          ),
          const SizedBox(height: 6),
          Text(
            'ريما بتقرأ الرد بالعربي أو الإنكليزي حسب لغة الرد نفسه.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: _testVoice,
            icon: const Icon(Icons.record_voice_over),
            label: const Text('جرّب صوت ريما'),
          ),
        ],
      ),
    );
  }
}
