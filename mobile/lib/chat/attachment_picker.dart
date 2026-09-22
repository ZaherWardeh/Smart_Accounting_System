import 'package:image_picker/image_picker.dart';

import '../models/models.dart';

/// Lets the user attach a document image (a bill, a receipt) to a message.
/// Behind an interface so tests don't need a real gallery.
abstract class AttachmentPicker {
  /// Opens the phone's gallery. Null when the user backs out.
  Future<RimaAttachment?> pickFromGallery();
}

class GalleryAttachmentPicker implements AttachmentPicker {
  const GalleryAttachmentPicker();

  @override
  Future<RimaAttachment?> pickFromGallery() async {
    // Downscale on the phone: a bill stays readable at 1600 px, and the upload
    // is a few hundred KB instead of a multi-megabyte camera original.
    final file = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600,
      maxHeight: 1600,
      imageQuality: 80,
    );
    if (file == null) return null;
    return RimaAttachment(bytes: await file.readAsBytes(), name: file.name);
  }
}
