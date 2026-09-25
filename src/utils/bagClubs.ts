import { getClub, isClubId } from '@/data/clubs';
import { BagClub, ClubId, Shot } from '@/types';

/** The Pi rejects anything outside these (club_vision.py). */
export const FACE_WIDTH_RANGE_MM = [55, 135] as const;
export const FACE_HEIGHT_RANGE_MM = [20, 80] as const;
export const MAX_BAG_CLUB_NAME = 40;

export const FACE_MEASURING_GUIDE = [
  'Sole the club on a table at its normal lie, face toward you.',
  'Width: heel to toe across the face along the leading edge, from where the hosel meets the face to the far edge of the toe. Wedges are typically 75–82 mm.',
  'Height: at the centre of the face, straight up from the leading edge to the top line. Wedges are typically 45–55 mm.',
  'A ruler to the nearest millimetre is enough; the Pi checks the camera’s view of the face against it.',
];

export function newBagClubId(): string {
  return `bag-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export interface BagClubDraft {
  name: string;
  baseClubId: ClubId;
  loftDeg: string;
  faceWidthMm: string;
  faceHeightMm: string;
}

const optionalNumber = (text: string): number | null | undefined => {
  if (!text.trim()) return null;
  const value = Number(text.replace(',', '.'));
  return Number.isFinite(value) ? value : undefined;
};

/** A saved club, or the reason the draft cannot be saved. */
export function bagClubFromDraft(draft: BagClubDraft, existing?: BagClub): BagClub | string {
  const name = draft.name.trim();
  if (!name) return 'Give the club a name, e.g. "Vokey SM10 56".';
  if (name.length > MAX_BAG_CLUB_NAME) return `Keep the name to ${MAX_BAG_CLUB_NAME} characters.`;
  const loft = optionalNumber(draft.loftDeg);
  const width = optionalNumber(draft.faceWidthMm);
  const height = optionalNumber(draft.faceHeightMm);
  if (loft === undefined || (loft !== null && (loft < 5 || loft > 70))) return 'Loft must be between 5° and 70°.';
  if (width === undefined || height === undefined) return 'Face sizes must be numbers in millimetres.';
  if ((width === null) !== (height === null)) return 'Enter both face width and face height, or neither.';
  if (width !== null && (width < FACE_WIDTH_RANGE_MM[0] || width > FACE_WIDTH_RANGE_MM[1])) {
    return `Face width must be ${FACE_WIDTH_RANGE_MM[0]}–${FACE_WIDTH_RANGE_MM[1]} mm.`;
  }
  if (height !== null && (height < FACE_HEIGHT_RANGE_MM[0] || height > FACE_HEIGHT_RANGE_MM[1])) {
    return `Face height must be ${FACE_HEIGHT_RANGE_MM[0]}–${FACE_HEIGHT_RANGE_MM[1]} mm.`;
  }
  return {
    id: existing?.id ?? newBagClubId(), name, baseClubId: draft.baseClubId,
    loftDeg: loft, faceWidthMm: width, faceHeightMm: height,
    createdAt: existing?.createdAt ?? new Date().toISOString(),
  };
}

export function draftFromBagClub(club: BagClub | null, baseClubId: ClubId): BagClubDraft {
  const text = (value: number | null | undefined) => (value == null ? '' : String(value));
  return {
    name: club?.name ?? '', baseClubId: club?.baseClubId ?? baseClubId,
    loftDeg: text(club?.loftDeg), faceWidthMm: text(club?.faceWidthMm), faceHeightMm: text(club?.faceHeightMm),
  };
}

/** What the Pi needs: the name for captures and, when measured, the face size. */
export function bagClubCommand(club: BagClub | null | undefined) {
  if (!club) return undefined;
  return {
    id: club.id, name: club.name,
    ...(club.faceWidthMm != null && club.faceHeightMm != null
      ? { faceWidthMm: club.faceWidthMm, faceHeightMm: club.faceHeightMm } : {}),
  };
}

/** A shot's club as the player named it, falling back to the club type. */
export function shotClubLabel(shot: Pick<Shot, 'clubId' | 'bagClubName'>): string {
  return shot.bagClubName ?? getClub(shot.clubId).label;
}

export function parseBagClubs(raw: string | null | undefined): BagClub[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is BagClub => Boolean(item) && typeof item.id === 'string' && typeof item.name === 'string'
        && isClubId(item.baseClubId))
      : [];
  } catch {
    return [];
  }
}
