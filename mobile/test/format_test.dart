import 'package:flutter_test/flutter_test.dart';
import 'package:rima_mobile/core/format.dart';
import 'package:rima_mobile/models/models.dart';

void main() {
  group('parseAmount', () {
    test('plain, decimal, thousands commas', () {
      expect(parseAmount('100'), 100);
      expect(parseAmount('12.5'), 12.5);
      expect(parseAmount('1,234.50'), 1234.5);
      expect(parseAmount('  7 '), 7);
    });

    test('Arabic-Indic digits and the Arabic decimal separator', () {
      expect(parseAmount('١٢٣'), 123);
      expect(parseAmount('١٢٫٥'), 12.5);
    });

    test('garbage and empty are null, not zero', () {
      expect(parseAmount(''), isNull);
      expect(parseAmount('abc'), isNull);
    });
  });

  group('balancing', () {
    TxLine d(double v) => TxLine(accId: 1, debit: v);
    TxLine c(double v) => TxLine(accId: 2, credit: v);

    test('equal debits and credits balance', () {
      expect(computeTotals([d(100), c(100)]).balanced, isTrue);
    });

    test('unequal does not', () {
      expect(computeTotals([d(100), c(99.99)]).balanced, isFalse);
    });

    test('an empty/zero entry is not "balanced"', () {
      expect(computeTotals(<TxLine>[]).balanced, isFalse);
      expect(computeTotals([d(0), c(0)]).balanced, isFalse);
    });

    test('float noise (0.1 + 0.2 vs 0.3) still counts as balanced', () {
      expect(0.1 + 0.2 == 0.3, isFalse); // the trap
      expect(computeTotals([d(0.1), d(0.2), c(0.3)]).balanced, isTrue);
    });
  });

  test('fmtNum groups thousands and trims trailing zeros', () {
    expect(fmtNum(305000), '305,000');
    expect(fmtNum(12.5), '12.5');
    expect(fmtNum(0), '0');
  });

  test('fmtDate is zero-padded ISO', () {
    expect(fmtDate(DateTime(2026, 3, 1)), '2026-03-01');
    expect(fmtDate(null), '—');
  });
}
