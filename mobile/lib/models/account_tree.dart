import 'models.dart';

class AccountNode {
  AccountNode(this.account);

  final Account account;
  final List<AccountNode> children = [];

  bool get isMaster => children.isNotEmpty;
}

/// Coded accounts before uncoded ones; two codes compare as plain strings
/// when they're the same width (which is what makes the parent-prefixed
/// scheme sort into depth-first order) and numerically otherwise, so a
/// hand-typed "5" still lands before "10".
int compareAccounts(Account a, Account b) {
  final ac = a.code, bc = b.code;
  final aHas = ac != null && ac.isNotEmpty;
  final bHas = bc != null && bc.isNotEmpty;
  if (aHas != bHas) return aHas ? -1 : 1;
  if (aHas && bHas) {
    if (ac.length != bc.length) {
      final an = int.tryParse(ac), bn = int.tryParse(bc);
      if (an != null && bn != null && an != bn) return an.compareTo(bn);
    }
    final c = ac.compareTo(bc);
    if (c != 0) return c;
  }
  return a.name.compareTo(b.name);
}

/// Builds the chart-of-accounts forest. An account whose parent no longer
/// exists is treated as a root instead of silently disappearing.
List<AccountNode> buildAccountTree(List<Account> accounts) {
  final nodes = {for (final a in accounts) a.id: AccountNode(a)};
  final roots = <AccountNode>[];
  for (final node in nodes.values) {
    final parent = node.account.parentAccount == null ? null : nodes[node.account.parentAccount];
    if (parent == null || identical(parent, node)) {
      roots.add(node);
    } else {
      parent.children.add(node);
    }
  }
  void sortRec(List<AccountNode> list) {
    list.sort((a, b) => compareAccounts(a.account, b.account));
    for (final n in list) {
      sortRec(n.children);
    }
  }

  sortRec(roots);
  return roots;
}

/// Ids of [id] plus everything underneath it - used to stop the parent
/// picker from offering an account's own descendants (which would create a
/// cycle in the chart of accounts).
Set<int> selfAndDescendantIds(List<Account> accounts, int id) {
  final childrenOf = <int, List<int>>{};
  for (final a in accounts) {
    final p = a.parentAccount;
    if (p != null) childrenOf.putIfAbsent(p, () => []).add(a.id);
  }
  final result = <int>{};
  final stack = [id];
  while (stack.isNotEmpty) {
    final cur = stack.removeLast();
    if (result.add(cur)) stack.addAll(childrenOf[cur] ?? const []);
  }
  return result;
}
