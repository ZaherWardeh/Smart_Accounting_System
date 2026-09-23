import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'chat/attachment_picker.dart';
import 'core/api_client.dart';
import 'core/settings.dart';
import 'core/system_settings.dart';
import 'screens/accounts_screen.dart';
import 'screens/chat_screen.dart';
import 'screens/home_screen.dart';
import 'screens/reports_screen.dart';
import 'screens/transactions_screen.dart';
import 'voice/voice_service.dart';

class RimaApp extends StatelessWidget {
  const RimaApp({
    super.key,
    required this.settings,
    required this.api,
    required this.voice,
    this.picker = const GalleryAttachmentPicker(),
    this.settingsOpener = const PlatformSystemSettingsOpener(),
  });

  final AppSettings settings;
  final ApiClient api;
  final VoiceService voice;
  final AttachmentPicker picker;
  final SystemSettingsOpener settingsOpener;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AppSettings>.value(value: settings),
        Provider<ApiClient>.value(value: api),
        Provider<VoiceService>.value(value: voice),
        Provider<AttachmentPicker>.value(value: picker),
        Provider<SystemSettingsOpener>.value(value: settingsOpener),
      ],
      child: MaterialApp(
        title: 'Rima',
        debugShowCheckedModeBanner: false,
        // Arabic locale => the whole UI (and the date picker) lays out right-to-left.
        locale: const Locale('ar'),
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        theme: ThemeData(
          useMaterial3: true,
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2F6F4F)),
        ),
        home: const AppShell(),
      ),
    );
  }
}

/// Bottom-nav shell. Tab order matters: HomeScreen's cards navigate by index.
class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  static const _chatTab = 4;

  int _index = 0;
  final Set<int> _built = {0};

  // Data tabs are rebuilt (and so re-fetch) every time you switch to them, so
  // they never show stale data after you changed something on another tab.
  // The chat tab is kept alive instead, so switching away doesn't lose the
  // conversation or cut off Rima mid-sentence.
  final List<int> _visits = List.filled(5, 0);

  void _select(int i) {
    setState(() {
      if (i != _chatTab && i != _index) _visits[i]++;
      _index = i;
      _built.add(i);
    });
  }

  Widget _page(int i) {
    if (!_built.contains(i)) return const SizedBox.shrink();
    switch (i) {
      case 0:
        return HomeScreen(onNavigate: _select);
      case 1:
        return const AccountsScreen();
      case 2:
        return const TransactionsScreen();
      case 3:
        return const ReportsScreen();
      default:
        return const ChatScreen();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: [
          for (var i = 0; i < 5; i++) KeyedSubtree(key: ValueKey('tab$i-${_visits[i]}'), child: _page(i)),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: _select,
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'الرئيسية'),
          NavigationDestination(icon: Icon(Icons.account_tree_outlined), selectedIcon: Icon(Icons.account_tree), label: 'الحسابات'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), selectedIcon: Icon(Icons.receipt_long), label: 'القيود'),
          NavigationDestination(icon: Icon(Icons.bar_chart_outlined), selectedIcon: Icon(Icons.bar_chart), label: 'التقارير'),
          NavigationDestination(icon: Icon(Icons.mic_none), selectedIcon: Icon(Icons.mic), label: 'ريما'),
        ],
      ),
    );
  }
}
