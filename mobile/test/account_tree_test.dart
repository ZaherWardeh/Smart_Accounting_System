import 'package:flutter_test/flutter_test.dart';
import 'package:rima_mobile/models/account_tree.dart';
import 'package:rima_mobile/models/models.dart';

Account acc(int id, String? code, String name, int? parent) =>
    Account(id: id, code: code, name: name, closeIn: 0, parentAccount: parent);

/// Depth-first flatten, the order the Accounts screen renders.
List<String> flatten(List<AccountNode> nodes) => [
      for (final n in nodes) ...[n.account.name, ...flatten(n.children)],
    ];

void main() {
  // A slice of the real hierarchical chart (Assets subtree + Liabilities root),
  // deliberately fed in scrambled order.
  final accounts = [
    acc(7, '0010301', 'صندوق', 4),
    acc(8, '002', 'المطاليب', null),
    acc(3, '00102', 'موجودات متداولة', 1),
    acc(1, '001', 'الموجودات', null),
    acc(5, '0010201', 'زبائن', 3),
    acc(4, '00103', 'موجودات جاهزة', 1),
    acc(2, '00101', 'موجودات ثابتة', 1),
    acc(9, '00201', 'المطاليب الثابتة', 8),
    acc(6, '001020101', 'زاهر', 5),
  ];

  test('builds the tree in depth-first order by code', () {
    final tree = buildAccountTree(accounts);

    expect(tree.map((n) => n.account.name), ['الموجودات', 'المطاليب']);
    expect(flatten(tree), [
      'الموجودات',
      'موجودات ثابتة', // 00101
      'موجودات متداولة', // 00102
      'زبائن', //   0010201
      'زاهر', //    001020101
      'موجودات جاهزة', // 00103
      'صندوق', //   0010301
      'المطاليب',
      'المطاليب الثابتة',
    ]);
  });

  test('master vs book comes from having children', () {
    final tree = buildAccountTree(accounts);
    final assets = tree.first;
    expect(assets.isMaster, isTrue);
    expect(assets.children.first.isMaster, isFalse); // موجودات ثابتة is a leaf
  });

  test('an account whose parent no longer exists becomes a root instead of vanishing', () {
    final tree = buildAccountTree([acc(1, '001', 'A', null), acc(99, '9', 'يتيم', 12345)]);
    expect(tree.map((n) => n.account.name), containsAll(['A', 'يتيم']));
  });

  test('an account listing itself as parent does not disappear or recurse forever', () {
    final tree = buildAccountTree([acc(1, '001', 'loop', 1)]);
    expect(tree.single.account.name, 'loop');
    expect(tree.single.children, isEmpty);
  });

  group('compareAccounts', () {
    test('coded accounts sort before uncoded ones', () {
      final list = [acc(1, null, 'زاد', null), acc(2, '5', 'ب', null)]..sort(compareAccounts);
      expect(list.map((a) => a.id), [2, 1]);
    });

    test('different-width hand-typed codes compare numerically', () {
      final list = [acc(1, '10', 'a', null), acc(2, '5', 'b', null)]..sort(compareAccounts);
      expect(list.map((a) => a.code), ['5', '10']);
    });

    test('same-width codes compare as strings (what keeps subtrees contiguous)', () {
      final list = [acc(1, '00103', 'a', null), acc(2, '00102', 'b', null)]..sort(compareAccounts);
      expect(list.map((a) => a.code), ['00102', '00103']);
    });
  });

  test('selfAndDescendantIds covers the whole subtree and nothing else', () {
    expect(selfAndDescendantIds(accounts, 3), {3, 5, 6}); // متداولة, زبائن, زاهر
    expect(selfAndDescendantIds(accounts, 6), {6});
    expect(selfAndDescendantIds(accounts, 8), {8, 9});
  });
}
