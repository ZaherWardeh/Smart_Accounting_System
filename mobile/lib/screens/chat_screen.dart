import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../chat/chat_controller.dart';
import '../core/api_client.dart';
import '../core/settings.dart';
import '../voice/voice_service.dart';
import '../widgets/common.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late final ChatController _chat;
  final _input = TextEditingController();
  final _scroll = ScrollController();
  int _lastCount = 0;
  bool _wasListening = false;

  @override
  void initState() {
    super.initState();
    _chat = ChatController(
      api: context.read<ApiClient>(),
      voice: context.read<VoiceService>(),
      settings: context.read<AppSettings>(),
    )..addListener(_onChat);
  }

  void _onChat() {
    if (_chat.listening) {
      // fill the box with the live transcript while the mic is open
      if (_input.text != _chat.partial) {
        _input.value = TextEditingValue(
          text: _chat.partial,
          selection: TextSelection.collapsed(offset: _chat.partial.length),
        );
      }
    } else if (_wasListening) {
      _input.clear(); // mic just closed: the transcript was sent (or thrown away)
    }
    _wasListening = _chat.listening;
    if (_chat.messages.length != _lastCount || _chat.sending) {
      _lastCount = _chat.messages.length;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });
    }
  }

  @override
  void dispose() {
    _chat.removeListener(_onChat);
    _chat.dispose();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send() {
    final text = _input.text;
    if (text.trim().isEmpty) return;
    _input.clear();
    _chat.send(text);
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<AppSettings>();
    return ChangeNotifierProvider<ChatController>.value(
      value: _chat,
      child: Consumer<ChatController>(
        builder: (context, chat, _) {
          return Scaffold(
            appBar: AppBar(
              title: const Row(
                children: [
                  CircleAvatar(radius: 14, child: Text('ر')),
                  SizedBox(width: 8),
                  Text('ريما'),
                ],
              ),
              actions: [
                IconButton(
                  tooltip: settings.autoSpeak ? 'إيقاف صوت ريما' : 'تشغيل صوت ريما',
                  icon: Icon(settings.autoSpeak ? Icons.volume_up : Icons.volume_off),
                  onPressed: () {
                    final muting = settings.autoSpeak;
                    settings.setAutoSpeak(!muting);
                    if (muting) chat.stopSpeaking(); // muting also cuts off whatever's being read now
                  },
                ),
                IconButton(tooltip: 'محادثة جديدة', icon: const Icon(Icons.add_comment_outlined), onPressed: chat.newConversation),
                IconButton(tooltip: 'الإعدادات', icon: const Icon(Icons.settings), onPressed: () => openSettings(context)),
              ],
            ),
            body: Column(
              children: [
                Expanded(child: _messageList(context, chat)),
                if (chat.notice != null) _noticeBar(context, chat),
                if (chat.speaking) _speakingBar(context, chat),
                if (chat.listening) _listeningBar(context, chat),
                _composer(context, chat),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _messageList(BuildContext context, ChatController chat) {
    if (chat.messages.isEmpty && !chat.sending) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.record_voice_over, size: 56, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 12),
              const Text(
                'اسأل ريما عن دليل الحسابات، حركة أي حساب، أو رصيده.\nاكتب سؤالك، أو اضغط على الميكروفون وتحدّث — وريما بتجاوبك بصوتها.',
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }
    final scheme = Theme.of(context).colorScheme;
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      itemCount: chat.messages.length + (chat.sending ? 1 : 0),
      itemBuilder: (context, i) {
        if (i == chat.messages.length) {
          return _bubble(context, child: const Text('ريما عم تفكر...', style: TextStyle(fontStyle: FontStyle.italic)), fromUser: false);
        }
        final m = chat.messages[i];
        final Color bg = m.fromUser ? scheme.primary : (m.isError ? scheme.errorContainer : scheme.surfaceContainerHighest);
        final Color fg = m.fromUser ? scheme.onPrimary : (m.isError ? scheme.onErrorContainer : scheme.onSurface);
        return _bubble(
          context,
          fromUser: m.fromUser,
          color: bg,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              SelectableText(m.text, style: TextStyle(color: fg, height: 1.5)),
              if (!m.fromUser && !m.isError)
                Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: InkWell(
                    onTap: () => chat.speaking ? chat.stopSpeaking() : chat.speak(m.text),
                    child: Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Icon(chat.speaking ? Icons.stop_circle_outlined : Icons.volume_up_outlined, size: 20, color: fg.withOpacity(0.7)),
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _bubble(BuildContext context, {required Widget child, required bool fromUser, Color? color}) {
    return Align(
      alignment: fromUser ? AlignmentDirectional.centerStart : AlignmentDirectional.centerEnd,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
        decoration: BoxDecoration(
          color: color ?? Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(16),
        ),
        child: child,
      ),
    );
  }

  Widget _noticeBar(BuildContext context, ChatController chat) => MaterialBanner(
        content: Text(chat.notice!),
        actions: [TextButton(onPressed: chat.dismissNotice, child: const Text('حسناً'))],
      );

  Widget _speakingBar(BuildContext context, ChatController chat) => Material(
        color: Theme.of(context).colorScheme.primaryContainer,
        child: ListTile(
          dense: true,
          leading: const Icon(Icons.graphic_eq),
          title: const Text('ريما عم تحكي...'),
          trailing: TextButton(onPressed: chat.stopSpeaking, child: const Text('إيقاف')),
        ),
      );

  Widget _listeningBar(BuildContext context, ChatController chat) => Material(
        color: Theme.of(context).colorScheme.errorContainer,
        child: ListTile(
          dense: true,
          leading: Icon(Icons.mic, color: Theme.of(context).colorScheme.error),
          title: Text(chat.partial.isEmpty ? 'عم سمعك... احكي هلق' : chat.partial),
        ),
      );

  Widget _composer(BuildContext context, ChatController chat) {
    final scheme = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: _input,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                decoration: InputDecoration(
                  hintText: 'اكتب سؤالك هون...',
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  isDense: true,
                ),
              ),
            ),
            const SizedBox(width: 6),
            IconButton.filledTonal(
              tooltip: 'إرسال',
              onPressed: chat.sending ? null : _send,
              icon: const Icon(Icons.send),
            ),
            const SizedBox(width: 4),
            IconButton.filled(
              tooltip: chat.listening ? 'إيقاف التسجيل' : 'تحدّث',
              style: IconButton.styleFrom(backgroundColor: chat.listening ? scheme.error : scheme.primary),
              onPressed: chat.sending ? null : chat.toggleListening,
              icon: Icon(chat.listening ? Icons.stop : Icons.mic),
            ),
          ],
        ),
      ),
    );
  }
}
