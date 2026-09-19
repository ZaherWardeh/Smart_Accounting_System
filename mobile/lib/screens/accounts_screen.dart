import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../models/account_tree.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class AccountsScreen extends StatefulWidget {
  const AccountsScreen({super.key});

  @override
  State<AccountsScreen> createState() => _AccountsScreenState();
}

class _AccountsScreenState extends State<AccountsScreen> {
  late Future<List<Account>> _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<ApiClient>().accounts();
  }

  void _reload() {
    final next = context.read<ApiClient>().accounts();
    next.ignore(); // a fast failure must not be reported as unhandled before FutureBuilder subscribes
    setState(() {
      _future = next;
    });
  }

  Future<void> _openForm(List<Account> all, {Account? editing}) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _AccountForm(all: all, editing: editing),
    );
    if (saved == true) _reload();
  }

  Future<void> _delete(Account a) async {
    if (!await confirmDialog(context, 'متأكد من حذف الحساب "${a.name}"؟')) return;
    if (!mounted) return;
    try {
      await context.read<ApiClient>().deleteAccount(a.id);
      _reload();
    } on ApiException catch (e) {
      if (mounted) showSnack(context, e.message); // e.g. 409: has children or transactions
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('دليل الحسابات'),
        actions: [
          IconButton(tooltip: 'تحديث', icon: const Icon(Icons.refresh), onPressed: _reload),
          IconButton(tooltip: 'الإعدادات', icon: const Icon(Icons.settings), onPressed: () => openSettings(context)),
        ],
      ),
      floatingActionButton: FutureBuilder<List<Account>>(
        future: _future,
        builder: (context, snap) => snap.hasData
            ? FloatingActionButton.extended(
                onPressed: () => _openForm(snap.data!),
                icon: const Icon(Icons.add),
                label: const Text('حساب جديد'),
              )
            : const SizedBox.shrink(),
      ),
      body: FutureBuilder<List<Account>>(
        future: _future,
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
          final accounts = snap.data!;
          if (accounts.isEmpty) return const Center(child: Text('لا يوجد حسابات بعد.'));
          final roots = buildAccountTree(accounts);
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.only(bottom: 96, top: 4),
              children: [
                for (final root in roots)
                  _AccountTile(node: root, depth: 0, onEdit: (a) => _openForm(accounts, editing: a), onDelete: _delete),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _AccountTile extends StatelessWidget {
  const _AccountTile({required this.node, required this.depth, required this.onEdit, required this.onDelete});

  final AccountNode node;
  final int depth;
  final void Function(Account) onEdit;
  final void Function(Account) onDelete;

  @override
  Widget build(BuildContext context) {
    final a = node.account;
    final title = Row(
      children: [
        if (a.code != null && a.code!.isNotEmpty) ...[Tag(a.code!), const SizedBox(width: 8)],
        Expanded(child: Text(a.name, style: const TextStyle(fontWeight: FontWeight.w500))),
        Tag(node.isMaster ? 'رئيسي' : 'فرعي', color: node.isMaster ? Colors.orange.shade800 : null),
      ],
    );
    final subtitle = Text(closeInLabelsAr[a.closeIn] ?? '${a.closeIn}', style: Theme.of(context).textTheme.bodySmall);
    final menu = PopupMenuButton<String>(
      tooltip: 'خيارات',
      onSelected: (v) => v == 'edit' ? onEdit(a) : onDelete(a),
      itemBuilder: (_) => const [
        PopupMenuItem(value: 'edit', child: Text('تعديل')),
        PopupMenuItem(value: 'delete', child: Text('حذف')),
      ],
    );
    final padding = EdgeInsetsDirectional.only(start: 12.0 * depth);

    if (!node.isMaster) {
      return Padding(
        padding: padding,
        child: ListTile(dense: true, title: title, subtitle: subtitle, trailing: menu),
      );
    }
    return Padding(
      padding: padding,
      child: ExpansionTile(
        initiallyExpanded: true,
        shape: const Border(),
        collapsedShape: const Border(),
        title: title,
        subtitle: subtitle,
        controlAffinity: ListTileControlAffinity.leading,
        trailing: menu,
        children: [
          for (final child in node.children)
            _AccountTile(node: child, depth: 1, onEdit: onEdit, onDelete: onDelete),
        ],
      ),
    );
  }
}

class _AccountForm extends StatefulWidget {
  const _AccountForm({required this.all, this.editing});

  final List<Account> all;
  final Account? editing;

  @override
  State<_AccountForm> createState() => _AccountFormState();
}

class _AccountFormState extends State<_AccountForm> {
  final _code = TextEditingController();
  final _name = TextEditingController();
  int _closeIn = 0;
  int? _parent;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final e = widget.editing;
    if (e != null) {
      _code.text = e.code ?? '';
      _name.text = e.name;
      _closeIn = e.closeIn;
      _parent = e.parentAccount;
    }
  }

  @override
  void dispose() {
    _code.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'اسم الحساب مطلوب');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final code = _code.text.trim();
    final input = AccountInput(
      code: code.isEmpty ? null : code,
      name: name,
      closeIn: _closeIn,
      parentAccount: _parent,
    );
    try {
      final api = context.read<ApiClient>();
      if (widget.editing != null) {
        await api.updateAccount(widget.editing!.id, input);
      } else {
        await api.createAccount(input);
      }
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // Can't pick itself or one of its own descendants as parent - that would
    // make a cycle in the chart of accounts.
    final excluded = widget.editing == null ? <int>{} : selfAndDescendantIds(widget.all, widget.editing!.id);
    final parents = widget.all.where((a) => !excluded.contains(a.id)).toList()..sort(compareAccounts);

    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.of(context).viewInsets.bottom + 16),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(widget.editing == null ? 'حساب جديد' : 'تعديل حساب', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            Row(
              children: [
                SizedBox(
                  width: 110,
                  child: TextField(
                    controller: _code,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'الرمز', hintText: '001', border: OutlineInputBorder()),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: _name,
                    decoration: const InputDecoration(labelText: 'اسم الحساب', border: OutlineInputBorder()),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<int>(
              value: _closeIn,
              decoration: const InputDecoration(labelText: 'نوع الإغلاق', border: OutlineInputBorder()),
              items: [
                for (final e in closeInLabelsAr.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
              ],
              onChanged: (v) => setState(() => _closeIn = v ?? 0),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<int?>(
              value: _parent,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'الحساب الأب', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem<int?>(value: null, child: Text('— بدون —')),
                for (final a in parents)
                  DropdownMenuItem<int?>(
                    value: a.id,
                    child: Text(a.code == null || a.code!.isEmpty ? a.name : '${a.code} — ${a.name}', overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: (v) => setState(() => _parent = v),
            ),
            if (_error != null) ...[
              const SizedBox(height: 10),
              Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('حفظ'),
            ),
          ],
        ),
      ),
    );
  }
}
