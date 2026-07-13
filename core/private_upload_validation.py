from __future__ import annotations

import io
import logging
import os
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from PIL import Image, UnidentifiedImageError


logger = logging.getLogger(
    "arolana.private_upload_validation"
)


# ============================================================================
# FILE SIGNATURES
# ============================================================================


PDF_MAGIC = b"%PDF-"

JPEG_MAGIC = b"\xff\xd8\xff"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

ZIP_MAGICS = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
)

WEBP_RIFF_MAGIC = b"RIFF"
WEBP_MAGIC = b"WEBP"

EBML_MAGIC = b"\x1a\x45\xdf\xa3"


# ============================================================================
# MIME TYPES
# ============================================================================


MIME_PDF = "application/pdf"

MIME_JPEG = "image/jpeg"

MIME_PNG = "image/png"

MIME_WEBP = "image/webp"

MIME_DOCX = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)

MIME_MP4 = "video/mp4"

MIME_WEBM = "video/webm"


# ============================================================================
# GENERAL CONSTANTS
# ============================================================================


DANGEROUS_EXTENSIONS = frozenset(
    {
        ".apk",
        ".app",
        ".bat",
        ".bin",
        ".cgi",
        ".cmd",
        ".com",
        ".cpl",
        ".dll",
        ".dmg",
        ".exe",
        ".hta",
        ".htm",
        ".html",
        ".iso",
        ".jar",
        ".js",
        ".jse",
        ".lnk",
        ".mjs",
        ".msi",
        ".php",
        ".php3",
        ".php4",
        ".php5",
        ".phar",
        ".pl",
        ".ps1",
        ".py",
        ".pyc",
        ".rb",
        ".scr",
        ".sh",
        ".svg",
        ".swf",
        ".vbe",
        ".vbs",
        ".wsf",
    }
)


MAX_HEADER_READ = 8192

MAX_IMAGE_PIXELS = 50_000_000

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


# ============================================================================
# POLICY MODEL
# ============================================================================


@dataclass(frozen=True)
class UploadPolicy:
    key: str

    allowed_extensions: frozenset[str]

    allowed_detected_types: frozenset[str]

    max_size_bytes: int

    require_image_verification: bool = False

    require_docx_verification: bool = False

    allow_empty_file: bool = False


# ============================================================================
# POLICIES
# ============================================================================


KYC_POLICY = UploadPolicy(
    key="kyc",
    allowed_extensions=frozenset(
        {
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_PDF,
            MIME_JPEG,
            MIME_PNG,
        }
    ),
    max_size_bytes=10 * 1024 * 1024,
    require_image_verification=True,
)


PAYMENT_PROOF_POLICY = UploadPolicy(
    key="payment_proof",
    allowed_extensions=frozenset(
        {
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_PDF,
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
        }
    ),
    max_size_bytes=8 * 1024 * 1024,
    require_image_verification=True,
)


CHAT_IMAGE_POLICY = UploadPolicy(
    key="chat_image",
    allowed_extensions=frozenset(
        {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
        }
    ),
    max_size_bytes=10 * 1024 * 1024,
    require_image_verification=True,
)


CHAT_ATTACHMENT_POLICY = UploadPolicy(
    key="chat_attachment",
    allowed_extensions=frozenset(
        {
            ".pdf",
            ".docx",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_PDF,
            MIME_DOCX,
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
        }
    ),
    max_size_bytes=15 * 1024 * 1024,
    require_image_verification=True,
    require_docx_verification=True,
)


DELIVERY_EVIDENCE_POLICY = UploadPolicy(
    key="delivery_evidence",
    allowed_extensions=frozenset(
        {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".mp4",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
            MIME_MP4,
        }
    ),
    max_size_bytes=50 * 1024 * 1024,
    require_image_verification=True,
)


RIDER_DOCUMENT_POLICY = UploadPolicy(
    key="rider_document",
    allowed_extensions=frozenset(
        {
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_PDF,
            MIME_JPEG,
            MIME_PNG,
        }
    ),
    max_size_bytes=10 * 1024 * 1024,
    require_image_verification=True,
)


RESUME_POLICY = UploadPolicy(
    key="resume",
    allowed_extensions=frozenset(
        {
            ".pdf",
            ".docx",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_PDF,
            MIME_DOCX,
        }
    ),
    max_size_bytes=5 * 1024 * 1024,
    require_docx_verification=True,
)


REVIEW_VIDEO_POLICY = UploadPolicy(
    key="review_video",
    allowed_extensions=frozenset(
        {
            ".mp4",
            ".webm",
            ".mov",
            ".m4v",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_MP4,
            MIME_WEBM,
            MIME_QUICKTIME,
            MIME_M4V,
        }
    ),
    max_size_bytes=150 * 1024 * 1024,
)


PRIVATE_PROFILE_IMAGE_POLICY = UploadPolicy(
    key="private_profile_image",
    allowed_extensions=frozenset(
        {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
        }
    ),
    max_size_bytes=10 * 1024 * 1024,
    require_image_verification=True,
)

SENSITIVE_PROFILE_FILE_POLICY = UploadPolicy(
    key="sensitive_profile_file",
    allowed_extensions=frozenset(
        {
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ),
    allowed_detected_types=frozenset(
        {
            MIME_PDF,
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
        }
    ),
    max_size_bytes=10 * 1024 * 1024,
    require_image_verification=True,
)
# ============================================================================
# FILE STREAM HELPERS
# ============================================================================


def _safe_tell(uploaded_file) -> int | None:
    try:
        return uploaded_file.tell()
    except Exception:
        return None


def _safe_seek(
    uploaded_file,
    position: int,
) -> bool:
    try:
        uploaded_file.seek(position)
        return True
    except Exception:
        return False


def _read_bytes(
    uploaded_file,
    size: int | None = None,
) -> bytes:
    """
    Read uploaded file bytes without permanently changing stream position.
    """
    original_position = _safe_tell(
        uploaded_file
    )

    _safe_seek(
        uploaded_file,
        0,
    )

    try:
        if size is None:
            data = uploaded_file.read()
        else:
            data = uploaded_file.read(
                size
            )

        return bytes(
            data or b""
        )

    finally:
        if original_position is not None:
            _safe_seek(
                uploaded_file,
                original_position,
            )
        else:
            _safe_seek(
                uploaded_file,
                0,
            )


def _file_size(
    uploaded_file,
) -> int:
    declared_size = getattr(
        uploaded_file,
        "size",
        None,
    )

    if declared_size is not None:
        try:
            return int(
                declared_size
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    original_position = _safe_tell(
        uploaded_file
    )

    try:
        _safe_seek(
            uploaded_file,
            0,
        )

        uploaded_file.seek(
            0,
            os.SEEK_END,
        )

        return int(
            uploaded_file.tell()
        )

    finally:
        if original_position is not None:
            _safe_seek(
                uploaded_file,
                original_position,
            )
        else:
            _safe_seek(
                uploaded_file,
                0,
            )


# ============================================================================
# EXTENSION HANDLING
# ============================================================================


def normalized_extension(
    filename: str,
) -> str:
    return Path(
        str(filename or "")
    ).suffix.lower()


def _extension_family(
    extension: str,
) -> str:
    if extension in {
        ".jpg",
        ".jpeg",
    }:
        return MIME_JPEG

    if extension == ".png":
        return MIME_PNG

    if extension == ".webp":
        return MIME_WEBP

    if extension == ".pdf":
        return MIME_PDF

    if extension == ".docx":
        return MIME_DOCX

    if extension == ".mp4":
        return MIME_MP4

    if extension == ".webm":
        return MIME_WEBM

    return ""


# ============================================================================
# TYPE DETECTION
# ============================================================================


def _looks_like_mp4(
    header: bytes,
) -> bool:
    """
    ISO Base Media File Format commonly places `ftyp`
    at byte offset 4.
    """
    return (
        len(header) >= 12
        and header[4:8] == b"ftyp"
    )


def _looks_like_webp(
    header: bytes,
) -> bool:
    return (
        len(header) >= 12
        and header[:4] == WEBP_RIFF_MAGIC
        and header[8:12] == WEBP_MAGIC
    )


def _looks_like_webm(
    header: bytes,
) -> bool:
    return header.startswith(
        EBML_MAGIC
    )


def _looks_like_zip(
    header: bytes,
) -> bool:
    return any(
        header.startswith(
            magic
        )
        for magic in ZIP_MAGICS
    )


def _verify_docx_structure(
    uploaded_file,
) -> bool:
    """
    Confirm that the upload is a ZIP package containing the minimum
    structures expected from a DOCX Open XML document.
    """
    data = _read_bytes(
        uploaded_file
    )

    if not data:
        return False

    try:
        with zipfile.ZipFile(
            io.BytesIO(data)
        ) as archive:
            names = set(
                archive.namelist()
            )

            return (
                "[Content_Types].xml"
                in names
                and "word/document.xml"
                in names
            )

    except (
        zipfile.BadZipFile,
        OSError,
        RuntimeError,
    ):
        return False


def detect_file_type(
    uploaded_file,
) -> str:
    header = _read_bytes(
        uploaded_file,
        MAX_HEADER_READ,
    )

    if header.startswith(
        PDF_MAGIC
    ):
        return MIME_PDF

    if header.startswith(
        JPEG_MAGIC
    ):
        return MIME_JPEG

    if header.startswith(
        PNG_MAGIC
    ):
        return MIME_PNG

    if _looks_like_webp(
        header
    ):
        return MIME_WEBP

    if _looks_like_mp4(
        header
    ):
        return MIME_MP4

    if _looks_like_webm(
        header
    ):
        return MIME_WEBM

    if _looks_like_zip(
        header
    ):
        if _verify_docx_structure(
            uploaded_file
        ):
            return MIME_DOCX

    return ""


# ============================================================================
# IMAGE VALIDATION
# ============================================================================


def verify_image_integrity(
    uploaded_file,
) -> None:
    """
    Decode and verify the image container using Pillow.
    """
    data = _read_bytes(
        uploaded_file
    )

    if not data:
        raise ValidationError(
            "The uploaded image is empty.",
            code="empty_image",
        )

    try:
        with Image.open(
            io.BytesIO(data)
        ) as image:
            image.verify()

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValidationError(
            (
                "Upload a valid, non-corrupted image file."
            ),
            code="invalid_image",
        ) from exc


# ============================================================================
# CORE VALIDATION
# ============================================================================


def validate_upload_against_policy(
    uploaded_file,
    policy: UploadPolicy,
) -> None:
    if uploaded_file in (
        None,
        "",
    ):
        return

    filename = str(
        getattr(
            uploaded_file,
            "name",
            "",
        )
        or ""
    ).strip()

    if not filename:
        raise ValidationError(
            "Uploaded files must have a filename.",
            code="missing_filename",
        )

    extension = normalized_extension(
        filename
    )

    if extension in DANGEROUS_EXTENSIONS:
        raise ValidationError(
            (
                "This file type is not permitted "
                "for security reasons."
            ),
            code="dangerous_extension",
        )

    if extension not in policy.allowed_extensions:
        allowed_text = ", ".join(
            sorted(
                policy.allowed_extensions
            )
        )

        raise ValidationError(
            (
                f"Unsupported file type. "
                f"Allowed extensions: {allowed_text}."
            ),
            code="extension_not_allowed",
        )

    size = _file_size(
        uploaded_file
    )

    if (
        not policy.allow_empty_file
        and size <= 0
    ):
        raise ValidationError(
            "Empty files are not allowed.",
            code="empty_file",
        )

    if size > policy.max_size_bytes:
        max_megabytes = (
            policy.max_size_bytes
            / 1024
            / 1024
        )

        raise ValidationError(
            (
                f"File is too large. "
                f"Maximum allowed size is "
                f"{max_megabytes:g} MB."
            ),
            code="file_too_large",
        )

    detected_type = detect_file_type(
        uploaded_file
    )

    if not detected_type:
        raise ValidationError(
            (
                "The actual file format could not be verified."
            ),
            code="unknown_file_signature",
        )

    if detected_type not in policy.allowed_detected_types:
        raise ValidationError(
            (
                "The file contents do not match an allowed format."
            ),
            code="detected_type_not_allowed",
        )

    expected_type = _extension_family(
        extension
    )

    if (
        expected_type
        and detected_type != expected_type
    ):
        raise ValidationError(
            (
                "The filename extension does not match "
                "the actual file contents."
            ),
            code="extension_content_mismatch",
        )

    if (
        policy.require_image_verification
        and detected_type
        in {
            MIME_JPEG,
            MIME_PNG,
            MIME_WEBP,
        }
    ):
        verify_image_integrity(
            uploaded_file
        )

    if (
        policy.require_docx_verification
        and detected_type == MIME_DOCX
        and not _verify_docx_structure(
            uploaded_file
        )
    ):
        raise ValidationError(
            "Upload a valid DOCX document.",
            code="invalid_docx",
        )

    _safe_seek(
        uploaded_file,
        0,
    )


# ============================================================================
# DECONSTRUCTIBLE DJANGO VALIDATOR
# ============================================================================


@deconstructible
class PrivateUploadValidator:
    """
    Migration-safe validator wrapper for Django model FileField/ImageField.
    """

    def __init__(
        self,
        policy_key: str,
    ):
        self.policy_key = policy_key

    def __call__(
        self,
        uploaded_file,
    ):
        policy = PRIVATE_UPLOAD_POLICIES.get(
            self.policy_key
        )

        if policy is None:
            raise ValidationError(
                (
                    "Upload security policy configuration is invalid."
                ),
                code="unknown_upload_policy",
            )

        validate_upload_against_policy(
            uploaded_file,
            policy,
        )

    def __eq__(
        self,
        other,
    ):
        return (
            isinstance(
                other,
                PrivateUploadValidator,
            )
            and self.policy_key
            == other.policy_key
        )


# ============================================================================
# POLICY REGISTRY
# ============================================================================


PRIVATE_UPLOAD_POLICIES = {
    KYC_POLICY.key: KYC_POLICY,
    PAYMENT_PROOF_POLICY.key: PAYMENT_PROOF_POLICY,
    CHAT_IMAGE_POLICY.key: CHAT_IMAGE_POLICY,
    CHAT_ATTACHMENT_POLICY.key: CHAT_ATTACHMENT_POLICY,
    DELIVERY_EVIDENCE_POLICY.key: DELIVERY_EVIDENCE_POLICY,
    RIDER_DOCUMENT_POLICY.key: RIDER_DOCUMENT_POLICY,
    RESUME_POLICY.key: RESUME_POLICY,
    REVIEW_VIDEO_POLICY.key: REVIEW_VIDEO_POLICY,
    PRIVATE_PROFILE_IMAGE_POLICY.key: PRIVATE_PROFILE_IMAGE_POLICY,
    SENSITIVE_PROFILE_FILE_POLICY.key: SENSITIVE_PROFILE_FILE_POLICY,
}


# ============================================================================
# READY-TO-IMPORT VALIDATORS
# ============================================================================


validate_kyc_upload = PrivateUploadValidator(
    "kyc"
)

validate_payment_proof_upload = PrivateUploadValidator(
    "payment_proof"
)

validate_chat_image_upload = PrivateUploadValidator(
    "chat_image"
)

validate_chat_attachment_upload = PrivateUploadValidator(
    "chat_attachment"
)

validate_delivery_evidence_upload = PrivateUploadValidator(
    "delivery_evidence"
)

validate_rider_document_upload = PrivateUploadValidator(
    "rider_document"
)

validate_resume_upload = PrivateUploadValidator(
    "resume"
)

validate_review_video_upload = PrivateUploadValidator(
    "review_video"
)

validate_private_profile_image_upload = PrivateUploadValidator(
    "private_profile_image"
)

validate_sensitive_profile_file_upload = PrivateUploadValidator(
    "sensitive_profile_file"
)