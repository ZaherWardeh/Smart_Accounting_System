import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../widgets/common.dart';

/// Shows the source document (bill image) saved with an entry, zoomable.
class DocumentViewerPage extends StatefulWidget {
  const DocumentViewerPage({super.key, required this.transactionId});

  final int transactionId;

  @override
  State<DocumentViewerPage> createState() => _DocumentViewerPageState();
}

class _DocumentViewerPageState extends State<DocumentViewerPage> {
  late Future<Uint8List> _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<ApiClient>().transactionDocument(widget.transactionId);
  }

  void _reload() {
    final next = context.read<ApiClient>().transactionDocument(widget.transactionId);
    next.ignore();
    setState(() {
      _future = next;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('مستند القيد ${widget.transactionId}')),
      body: FutureBuilder<Uint8List>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            final err = snap.error;
            return ErrorView(
              message: err is ApiException ? err.message : 'تعذر تحميل المستند',
              onRetry: _reload,
              showSettings: err is ApiException && err.isConnection,
            );
          }
          return InteractiveViewer(
            key: const Key('document-viewer'),
            minScale: 0.8,
            maxScale: 6,
            child: Center(child: Image.memory(snap.data!, fit: BoxFit.contain)),
          );
        },
      ),
    );
  }
}
