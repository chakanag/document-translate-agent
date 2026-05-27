from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


JOB_STATUSES = {
    "queued",
    "extracting",
    "extracted",
    "detecting_language",
    "language_detected",
    "translating",
    "translated",
    "preview_ready",
    "verified",
    "exporting",
    "completed",
    "failed",
    "cancelled",
}


@dataclass
class DocumentBlock:
    id: str
    type: str
    sourceText: str
    order: int
    translatedText: Optional[str] = None
    pageNumber: Optional[int] = None
    sheetName: Optional[str] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    fontSize: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.bbox is not None:
            data["bbox"] = list(self.bbox)
        return data


@dataclass
class TranslationJob:
    id: str
    originalFileName: str
    fileType: str
    sourceLanguage: Optional[str]
    targetLanguage: str
    outputFormat: str
    aiProvider: str
    status: str
    createdAt: str
    updatedAt: str
    completedAt: Optional[str] = None
    errorMessage: Optional[str] = None
    originalPath: Optional[str] = None
    exportedPath: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    userId: Optional[str] = None
    ocrEngine: str = "none"  # "none" | "tesseract" | "claude_vision"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class User:
    id: str
    username: str
    role: str       # 'user' | 'admin'
    isActive: bool
    createdAt: str
    updatedAt: str
    email: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "isActive": self.isActive,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
            "email": self.email,
        }


@dataclass
class Session:
    id: str
    userId: str
    createdAt: str
    expiresAt: str
