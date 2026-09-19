final _arabicLetter = RegExp(r'[؀-ۿݐ-ݿ]');
final _anyLetter = RegExp(r'[A-Za-z؀-ۿݐ-ݿ]');

/// True when most of the letters in [text] are Arabic - decides which
/// text-to-speech voice reads it.
bool isArabicText(String text) {
  var arabic = 0, letters = 0;
  for (final rune in text.runes) {
    final ch = String.fromCharCode(rune);
    if (_arabicLetter.hasMatch(ch)) {
      arabic++;
      letters++;
    } else if (_anyLetter.hasMatch(ch)) {
      letters++;
    }
  }
  return letters > 0 && arabic / letters >= 0.3;
}

/// Turns Rima's chat reply (which can contain markdown from the model) into
/// something a speech engine reads naturally: no asterisks/backticks/pipes
/// spoken aloud, no URLs, and a pause at each line break.
String cleanForSpeech(String text) {
  var t = text.replaceAll(RegExp(r'```[\s\S]*?```'), ' ');
  t = t.replaceAll(RegExp(r'https?://\S+'), ' ');
  final lines = <String>[];
  for (var line in t.split(RegExp(r'\r?\n'))) {
    line = line.replaceFirst(RegExp(r'^\s*#{1,6}\s*'), '');
    line = line.replaceFirst(RegExp(r'^\s*[-*•]\s+'), '');
    line = line.replaceFirst(RegExp(r'^\s*\d+[.)]\s+'), '');
    line = line.replaceAll(RegExp(r'[*_`~|>#]+'), ' ');
    line = line.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (line.isEmpty) continue;
    if (!RegExp(r'[.!?؟،,:;]$').hasMatch(line)) line = '$line.';
    lines.add(line);
  }
  return lines.join(' ');
}

/// Android's TTS engine rejects very long inputs, so long replies are read in
/// sentence-sized pieces instead of one call.
List<String> chunkForSpeech(String text, {int maxLen = 3000}) {
  if (text.length <= maxLen) return text.isEmpty ? const [] : [text];
  final chunks = <String>[];
  var current = StringBuffer();
  void flush() {
    if (current.isNotEmpty) chunks.add(current.toString().trim());
    current = StringBuffer();
  }

  for (final sentence in text.split(RegExp(r'(?<=[.!?؟])\s+'))) {
    if (sentence.length > maxLen) {
      flush();
      for (var i = 0; i < sentence.length; i += maxLen) {
        chunks.add(sentence.substring(i, i + maxLen > sentence.length ? sentence.length : i + maxLen));
      }
      continue;
    }
    if (current.length + sentence.length + 1 > maxLen) flush();
    if (current.isNotEmpty) current.write(' ');
    current.write(sentence);
  }
  flush();
  return chunks.where((c) => c.isNotEmpty).toList();
}
