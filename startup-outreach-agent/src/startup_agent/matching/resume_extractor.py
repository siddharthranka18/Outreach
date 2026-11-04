"""Resume PDF extraction and profile supplementation utility."""

import logging
from pathlib import Path
import re
from typing import List, Optional, Set

from startup_agent.matching.profile import CandidateProfile

logger = logging.getLogger("startup_agent.matching.resume")


class ResumeExtractor:
    """Safely extracts text and technical signals from local PDF resumes."""

    # Curated technical vocabulary to extract from unstructured resume text
    KNOWN_TECH_VOCABULARY = {
        "python", "javascript", "typescript", "java", "c++", "c#", "go", "golang", "rust",
        "react", "react native", "node.js", "express.js", "fastapi", "django", "flask",
        "mysql", "postgresql", "mongodb", "redis", "firebase", "sqlite", "qdrant",
        "langchain", "langgraph", "rag", "retrieval-augmented generation", "docker",
        "kubernetes", "git", "github", "postman", "expo", "eas build", "bullmq",
        "socket.io", "rest apis", "mvc", "system design", "caching", "embeddings",
        "machine learning", "deep learning", "nlp", "computer vision", "llms",
        "graphql", "aws", "gcp", "azure"
    }

    def __init__(self, resume_path: Optional[Path] = None) -> None:
        self.resume_path = resume_path

    def extract_text(self, path: Optional[Path] = None) -> str:
        """Extract plain text content from a PDF resume file.

        Args:
            path: Target PDF file path.

        Returns:
            str: Extracted text content, or empty string on failure.
        """
        target_path = path or self.resume_path
        if not target_path or not target_path.exists():
            logger.info("Resume file not found or path not specified. Relying on configured profile.")
            return ""

        try:
            import pypdf
            reader = pypdf.PdfReader(str(target_path))
            extracted_pages: List[str] = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                extracted_pages.append(text)

            full_text = "\n".join(extracted_pages)
            logger.info("Extracted %d characters from resume PDF.", len(full_text))
            return full_text
        except Exception as exc:
            logger.warning("Failed to extract text from resume: %s", exc)
            return ""

    def extract_skills_from_text(self, text: str) -> Set[str]:
        """Identify known technical skills within extracted resume text."""
        if not text or not text.strip():
            return set()

        text_lower = text.lower()
        found_skills: Set[str] = set()

        for skill in self.KNOWN_TECH_VOCABULARY:
            # Word boundary regex matching to avoid substring collisions
            pattern = r"(?<!\w)" + re.escape(skill) + r"(?!\w)"
            if re.search(pattern, text_lower):
                found_skills.add(skill)

        return found_skills

    def supplement_profile(
        self,
        profile: CandidateProfile,
        resume_path: Optional[Path] = None,
    ) -> CandidateProfile:
        """Supplement a verified profile with newly discovered skills from a resume.

        Rule:
            Manually configured profile data is NEVER overwritten. Only non-conflicting
            supplemental skills are merged into tools/languages.
        """
        text = self.extract_text(resume_path)
        if not text:
            return profile

        extracted_skills = self.extract_skills_from_text(text)
        existing_skills = profile.all_skills

        # Append novel skills into tools category without altering existing entries
        for skill in extracted_skills:
            if skill not in existing_skills:
                profile.skills.tools.append(skill.title())

        logger.info(
            "Supplemented profile with %d novel skill signals from resume.",
            len(extracted_skills - existing_skills),
        )
        return profile
