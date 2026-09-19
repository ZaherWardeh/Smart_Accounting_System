import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../models/models.dart';
import '../widgets/common.dart';

String? _isoDate(DateTime? d) => d == null ? null : fmtDate(d);

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  late Future<List<ChartAccount>> _chart;

  @override
  void initState() {
    super.initState();
    _chart = context.read<ApiClient>().chartOfAccounts();
  }

  void _reload() {
    final next = context.read<ApiClient>().chartOfAccounts();
    next.ignore(); // a fast failure must not be reported as unhandled before FutureBuilder subscribes
    setState(() {
      _chart = next;
    });
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('التقارير'),
          actions: [
            IconButton(tooltip: 'الإعدادات', icon: const Icon(Icons.settings), onPressed: () => openSettings(context)),
          ],
          bottom: const TabBar(tabs: [Tab(text: 'كشف حساب'), Tab(text: 'رصيد الحسابات')]),
        ),
        body: FutureBuilder<List<ChartAccount>>(
          future: _chart,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              final err = snap.error;
              return ErrorView(
                message: err is ApiException ? err.message : 'حدث خطأ غير متوقع',
                onRetry: _reload,
                showSettings: err is ApiException && err.isConnection,
              );
            }
            final chart = snap.data!;
            return TabBarView(children: [_StatementTab(chart: chart), _BalanceTab(chart: chart)]);
          },
        ),
      ),
    );
  }
}

class _StatementTab extends StatefulWidget {
  const _StatementTab({required this.chart});

  final List<ChartAccount> chart;

  @override
  State<_StatementTab> createState() => _StatementTabState();
}

class _StatementTabState extends State<_StatementTab> with AutomaticKeepAliveClientMixin {
  int? _accId;
  DateTime? _from;
  DateTime? _to;
  bool _loading = false;
  String? _error;
  List<StatementRow>? _rows;

  @override
  bool get wantKeepAlive => true;

  Future<void> _run() async {
    if (_accId == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = await context.read<ApiClient>().statement(_accId!, dateFrom: _isoDate(_from), dateTo: _isoDate(_to));
      if (mounted) setState(() => _rows = rows);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final rows = _rows;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        DropdownButtonFormField<int>(
          value: _accId,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'الحساب', border: OutlineInputBorder()),
          items: [
            for (final a in widget.chart) DropdownMenuItem(value: a.id, child: Text(a.label, overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (v) => setState(() => _accId = v),
        ),
        const SizedBox(height: 6),
        Text(
          'إذا كان الحساب رئيسياً، بيشمل الكشف حركة كل الحسابات الفرعية تحته.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(child: DateButton(label: 'من تاريخ', value: _from, onChanged: (d) => setState(() => _from = d))),
            const SizedBox(width: 8),
            Expanded(child: DateButton(label: 'إلى تاريخ', value: _to, onChanged: (d) => setState(() => _to = d))),
          ],
        ),
        const SizedBox(height: 10),
        FilledButton(
          onPressed: (_accId == null || _loading) ? null : _run,
          child: _loading
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('عرض الكشف'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        if (rows != null) ...[
          const SizedBox(height: 16),
          if (rows.isEmpty)
            const Center(child: Text('لا يوجد حركة ضمن هذا النطاق.'))
          else ...[
            Row(
              children: [
                Expanded(child: StatTile(label: 'إجمالي مدين', value: fmtNum(rows.fold(0.0, (s, r) => s + r.debit)))),
                const SizedBox(width: 8),
                Expanded(child: StatTile(label: 'إجمالي دائن', value: fmtNum(rows.fold(0.0, (s, r) => s + r.credit)))),
              ],
            ),
            const SizedBox(height: 8),
            for (final r in rows)
              Card(
                child: ListTile(
                  dense: true,
                  title: Text('${r.date ?? '—'}  ·  ${r.accName ?? ''}'),
                  subtitle: (r.description == null || r.description!.isEmpty) ? null : Text(r.description!),
                  trailing: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      if (r.debit != 0) Text('مدين ${fmtNum(r.debit)}'),
                      if (r.credit != 0) Text('دائن ${fmtNum(r.credit)}'),
                    ],
                  ),
                ),
              ),
          ],
        ],
      ],
    );
  }
}

class _BalanceTab extends StatefulWidget {
  const _BalanceTab({required this.chart});

  final List<ChartAccount> chart;

  @override
  State<_BalanceTab> createState() => _BalanceTabState();
}

class _BalanceTabState extends State<_BalanceTab> with AutomaticKeepAliveClientMixin {
  final Set<int> _selected = {};
  DateTime? _asOf;
  DateTime? _from;
  DateTime? _to;
  bool _loading = false;
  String? _error;
  BalanceResult? _result;

  @override
  bool get wantKeepAlive => true;

  Future<void> _pickAccounts() async {
    final picked = await showDialog<Set<int>>(
      context: context,
      builder: (_) => _AccountPickerDialog(chart: widget.chart, initial: _selected),
    );
    if (picked != null) setState(() => _selected..clear()..addAll(picked));
  }

  Future<void> _run() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await context.read<ApiClient>().balance(
            _selected.toList(),
            asOfDate: _isoDate(_asOf),
            dateFrom: _isoDate(_from),
            dateTo: _isoDate(_to),
          );
      if (mounted) setState(() => _result = result);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final result = _result;
    final byId = {for (final a in widget.chart) a.id: a};
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        OutlinedButton.icon(
          onPressed: _pickAccounts,
          icon: const Icon(Icons.checklist),
          label: Text(_selected.isEmpty ? 'اختر حساب أو أكثر' : 'تم اختيار ${_selected.length}'),
        ),
        if (_selected.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final id in _selected)
                InputChip(
                  label: Text(byId[id]?.label ?? '$id'),
                  onDeleted: () => setState(() => _selected.remove(id)),
                ),
            ],
          ),
        ],
        const SizedBox(height: 8),
        Text(
          '"كتاريخ" لحسابات الميزانية العمومية، و"من/إلى" لحسابات الأرباح والمصاريف.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 8),
        DateButton(label: 'كتاريخ (ميزانية عمومية)', value: _asOf, onChanged: (d) => setState(() => _asOf = d)),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(child: DateButton(label: 'من تاريخ', value: _from, onChanged: (d) => setState(() => _from = d))),
            const SizedBox(width: 8),
            Expanded(child: DateButton(label: 'إلى تاريخ', value: _to, onChanged: (d) => setState(() => _to = d))),
          ],
        ),
        const SizedBox(height: 10),
        FilledButton(
          onPressed: (_selected.isEmpty || _loading) ? null : _run,
          child: _loading
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('احسب الرصيد'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        if (result != null) ...[
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(child: StatTile(label: 'إجمالي مدين', value: fmtNum(result.debit))),
              const SizedBox(width: 8),
              Expanded(child: StatTile(label: 'إجمالي دائن', value: fmtNum(result.credit))),
              const SizedBox(width: 8),
              Expanded(child: StatTile(label: 'الصافي', value: fmtNum(result.net))),
            ],
          ),
          const SizedBox(height: 8),
          for (final b in result.breakdown)
            Card(
              child: ListTile(
                dense: true,
                title: Text(b.error != null ? 'حساب ${b.accId}' : '${b.code == null ? '' : '${b.code} — '}${b.accName ?? ''}'),
                subtitle: b.error != null
                    ? Text(b.error!)
                    : Text('مدين ${fmtNum(b.debit)}  ·  دائن ${fmtNum(b.credit)}'),
                trailing: b.error != null ? null : Text(fmtNum(b.net), style: const TextStyle(fontWeight: FontWeight.w600)),
              ),
            ),
        ],
      ],
    );
  }
}

class _AccountPickerDialog extends StatefulWidget {
  const _AccountPickerDialog({required this.chart, required this.initial});

  final List<ChartAccount> chart;
  final Set<int> initial;

  @override
  State<_AccountPickerDialog> createState() => _AccountPickerDialogState();
}

class _AccountPickerDialogState extends State<_AccountPickerDialog> {
  late final Set<int> _picked = {...widget.initial};
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final q = _query.trim();
    final shown = widget.chart.where((a) => q.isEmpty || a.label.contains(q)).toList();
    return AlertDialog(
      title: const Text('اختر الحسابات'),
      contentPadding: const EdgeInsets.fromLTRB(8, 12, 8, 0),
      content: SizedBox(
        width: double.maxFinite,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: TextField(
                decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'بحث', isDense: true),
                onChanged: (v) => setState(() => _query = v),
              ),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final a in shown)
                    CheckboxListTile(
                      dense: true,
                      value: _picked.contains(a.id),
                      title: Text('${a.label}${a.isBook ? '' : ' (رئيسي)'}'),
                      onChanged: (v) => setState(() => v == true ? _picked.add(a.id) : _picked.remove(a.id)),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('إلغاء')),
        FilledButton(onPressed: () => Navigator.pop(context, _picked), child: const Text('تم')),
      ],
    );
  }
}
