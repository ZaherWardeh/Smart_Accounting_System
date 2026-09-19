import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.onNavigate});

  /// Switches the shell's bottom-nav tab (see the tab indices in app.dart).
  final void Function(int tab) onNavigate;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<Summary> _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<ApiClient>().summary();
  }

  void _reload() {
    final next = context.read<ApiClient>().summary();
    next.ignore(); // a fast failure must not be reported as unhandled before FutureBuilder subscribes
    setState(() {
      _future = next;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('نظام المحاسبة الذكي'),
        actions: [
          IconButton(
            tooltip: 'الإعدادات',
            icon: const Icon(Icons.settings),
            onPressed: () => openSettings(context),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => _reload(),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(), // so pull-to-refresh works on short content
          padding: const EdgeInsets.all(16),
          children: [
            Text('ملخص مالي', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            FutureBuilder<Summary>(
              future: _future,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: CircularProgressIndicator()),
                  );
                }
                if (snap.hasError) {
                  final err = snap.error;
                  return ErrorView(
                    message: err is ApiException ? err.message : 'حدث خطأ غير متوقع',
                    onRetry: _reload,
                    showSettings: err is ApiException && err.isConnection,
                  );
                }
                final s = snap.data!;
                if (s.message != null) {
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: Text(s.message!, textAlign: TextAlign.center),
                  );
                }
                return Row(
                  children: [
                    Expanded(child: StatTile(label: 'الإيرادات', value: fmtNum(s.income ?? 0))),
                    const SizedBox(width: 8),
                    Expanded(child: StatTile(label: 'المصاريف', value: fmtNum(s.expense ?? 0))),
                    const SizedBox(width: 8),
                    Expanded(child: StatTile(label: 'الرصيد', value: fmtNum(s.balance ?? 0))),
                  ],
                );
              },
            ),
            const SizedBox(height: 20),
            _NavCard(
              icon: Icons.account_tree,
              title: 'الحسابات',
              subtitle: 'دليل الحسابات على شكل شجرة، إضافة وتعديل وحذف',
              onTap: () => widget.onNavigate(1),
            ),
            _NavCard(
              icon: Icons.receipt_long,
              title: 'القيود المحاسبية',
              subtitle: 'استعراض القيود وإضافة قيد جديد متوازن',
              onTap: () => widget.onNavigate(2),
            ),
            _NavCard(
              icon: Icons.bar_chart,
              title: 'التقارير',
              subtitle: 'كشف حساب وأرصدة الحسابات',
              onTap: () => widget.onNavigate(3),
            ),
            _NavCard(
              icon: Icons.mic,
              title: 'ريما — المحاسبة الذكية',
              subtitle: 'اسأل بالكتابة أو بصوتك، وريما بتجاوبك بالصوت',
              onTap: () => widget.onNavigate(4),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavCard extends StatelessWidget {
  const _NavCard({required this.icon, required this.title, required this.subtitle, required this.onTap});

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: Icon(icon, color: Theme.of(context).colorScheme.primary),
        title: Text(title),
        subtitle: Text(subtitle),
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
