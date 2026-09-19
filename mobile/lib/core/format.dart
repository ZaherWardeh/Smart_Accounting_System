import 'package:intl/intl.dart';

import '../models/models.dart';

final _numberFormat = NumberFormat('#,##0.##', 'en_US');

String fmtNum(num n) => _numberFormat.format(n);

String fmtDate(DateTime? d) {
  if (d == null) return '—';
  String two(int v) => v.toString().padLeft(2, '0');
  return '${d.year.toString().padLeft(4, '0')}-${two(d.month)}-${two(d.day)}';
}

/// Parses what a user types into an amount field: tolerates Arabic-Indic
/// digits (٠-٩), the Arabic decimal separator (٫) and thousands commas.
/// Returns null for anything that isn't a number.
double? parseAmount(String raw) {
  var s = raw.trim();
  if (s.isEmpty) return null;
  const arabicDigits = '٠١٢٣٤٥٦٧٨٩';
  final buf = StringBuffer();
  for (final rune in s.runes) {
    final ch = String.fromCharCode(rune);
    final idx = arabicDigits.indexOf(ch);
    if (idx >= 0) {
      buf.write(idx);
    } else if (ch == '٫') {
      buf.write('.');
    } else if (ch == ',' || ch == '٬' || ch == ' ') {
      // thousands separator - drop
    } else {
      buf.write(ch);
    }
  }
  s = buf.toString();
  return double.tryParse(s);
}

/// Rounds to cents so client-side sums agree with what the server checks.
double roundCents(double v) => (v * 100).roundToDouble() / 100;

class TxTotals {
  const TxTotals(this.debit, this.credit);

  final double debit;
  final double credit;

  bool get balanced => debit > 0 && roundCents(debit) == roundCents(credit);
}

TxTotals computeTotals(Iterable<TxLine> lines) {
  var d = 0.0, c = 0.0;
  for (final l in lines) {
    d += l.debit;
    c += l.credit;
  }
  return TxTotals(roundCents(d), roundCents(c));
}
