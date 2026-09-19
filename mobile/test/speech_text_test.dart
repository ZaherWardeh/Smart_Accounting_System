import 'package:flutter_test/flutter_test.dart';
import 'package:rima_mobile/voice/speech_text.dart';

void main() {
  group('isArabicText', () {
    test('Arabic and English', () {
      expect(isArabicText('رصيد الصندوق هو 800 مدين'), isTrue);
      expect(isArabicText('The cash balance is 800 debit'), isFalse);
    });

    test('mostly-Arabic text with an English word still reads as Arabic', () {
      expect(isArabicText('حساب الـ Cash رصيده مدين'), isTrue);
    });

    test('digits/punctuation only is not Arabic (no letters to judge by)', () {
      expect(isArabicText('1,234.50'), isFalse);
      expect(isArabicText(''), isFalse);
    });
  });

  group('cleanForSpeech', () {
    test('strips markdown so symbols are not read out', () {
      final out = cleanForSpeech('**رصيد الصندوق:** `800` مدين');
      expect(out, isNot(contains('*')));
      expect(out, isNot(contains('`')));
      expect(out, contains('رصيد الصندوق'));
      expect(out, contains('800'));
    });

    test('drops bullets/numbering/headings and pauses between lines', () {
      final out = cleanForSpeech('## الحسابات\n- الصندوق: 800\n- البنك: 500\n1. الخلاصة');
      expect(out, isNot(contains('#')));
      expect(out, isNot(contains('- ')));
      expect(out, 'الحسابات. الصندوق: 800. البنك: 500. الخلاصة.');
    });

    test('removes URLs and fenced code', () {
      final out = cleanForSpeech('شوف https://example.com/x الآن\n```\nprint(1)\n```');
      expect(out, isNot(contains('http')));
      expect(out, isNot(contains('print')));
    });

    test('keeps existing sentence punctuation instead of doubling it', () {
      expect(cleanForSpeech('Hello there.'), 'Hello there.');
      expect(cleanForSpeech('شو رصيدك؟'), 'شو رصيدك؟');
    });

    test('empty / markdown-only input becomes empty', () {
      expect(cleanForSpeech('  \n ** \n'), '');
    });
  });

  group('chunkForSpeech', () {
    test('short text is one chunk; empty is none', () {
      expect(chunkForSpeech('مرحبا.'), ['مرحبا.']);
      expect(chunkForSpeech(''), isEmpty);
    });

    test('long text splits on sentence boundaries under the limit', () {
      const sentence = 'هذه جملة طويلة نوعاً ما للاختبار.';
      final text = List.filled(50, sentence).join(' ');
      final chunks = chunkForSpeech(text, maxLen: 200);
      expect(chunks.length, greaterThan(1));
      expect(chunks.every((c) => c.length <= 200), isTrue);
      expect(chunks.every((c) => c.endsWith('.')), isTrue); // never cut mid-sentence
      expect(chunks.join(' '), text);
    });

    test('a single sentence longer than the limit is hard-split, nothing lost', () {
      final text = 'ا' * 450;
      final chunks = chunkForSpeech(text, maxLen: 200);
      expect(chunks.join(), text);
      expect(chunks.every((c) => c.length <= 200), isTrue);
    });
  });
}
