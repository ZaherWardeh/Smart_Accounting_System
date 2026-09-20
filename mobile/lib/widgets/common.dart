import 'package:flutter/material.dart';

import '../screens/settings_screen.dart';

/// Shown when a load fails. If the failure was "can't reach the server" it
/// also offers a shortcut to the server-URL setting, since that's by far the
/// most likely fix.
class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, required this.onRetry, this.showSettings = false});

  final String message;
  final VoidCallback onRetry;
  final bool showSettings;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off, size: 48, color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('إعادة المحاولة'),
                ),
                if (showSettings)
                  OutlinedButton.icon(
                    onPressed: () => openSettings(context),
                    icon: const Icon(Icons.settings),
                    label: const Text('إعدادات الخادم'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

void openSettings(BuildContext context) {
  Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const SettingsScreen()));
}

class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.label, required this.value, this.color});

  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: scheme.primaryContainer.withOpacity(0.5),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 2),
          Text(
            value,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600, color: color),
          ),
        ],
      ),
    );
  }
}

/// A rounded, outlined tag - used for account codes and master/book badges.
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key, this.color});

  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.primary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: c.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(text, style: TextStyle(fontSize: 11, color: c, fontWeight: FontWeight.w500)),
    );
  }
}

Future<bool> confirmDialog(BuildContext context, String message, {String confirmLabel = 'حذف'}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(confirmLabel),
        ),
      ],
    ),
  );
  return result ?? false;
}

void showSnack(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// A date field that shows "من تاريخ"-style hint text until a date is picked.
class DateButton extends StatelessWidget {
  const DateButton({super.key, required this.label, required this.value, required this.onChanged});

  final String label;
  final DateTime? value;
  final ValueChanged<DateTime?> onChanged;

  @override
  Widget build(BuildContext context) {
    String two(int v) => v.toString().padLeft(2, '0');
    final text = value == null ? label : '${value!.year}-${two(value!.month)}-${two(value!.day)}';
    return OutlinedButton.icon(
      style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 12)),
      icon: const Icon(Icons.event, size: 18),
      label: Text(text, overflow: TextOverflow.ellipsis),
      onPressed: () async {
        final now = DateTime.now();
        final picked = await showDatePicker(
          context: context,
          initialDate: value ?? now,
          firstDate: DateTime(2000),
          lastDate: DateTime(now.year + 5),
        );
        if (picked != null) onChanged(picked);
      },
      onLongPress: value == null ? null : () => onChanged(null), // long-press clears
    );
  }
}
