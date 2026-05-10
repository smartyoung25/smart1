from enum import Enum


class FarmTier(str, Enum):
    MANUAL = "manual"        # Tier 1 — AI recommendation → farmer checklist
    SEMI_AUTO = "semi_auto"  # Tier 2 — recommendation → approval modal → actuator
    AUTO = "auto"            # Tier 2+ — threshold breach → immediate execution


TIER_LABELS_KO: dict[FarmTier, str] = {
    FarmTier.MANUAL: "수동",
    FarmTier.SEMI_AUTO: "반자동",
    FarmTier.AUTO: "완전자동",
}
