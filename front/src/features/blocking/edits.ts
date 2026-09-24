import type { BlockingCameraOverride, BlockingDocument, BlockingShot, Vec3 } from './types';

/**
 * Manual 白膜 edits as pure document transforms. The drag editor and the
 * shot picker produce one of these; the studio applies it locally at once
 * and persists the whole document with `PATCH …/blocking` (the backend
 * re-sanitizes it, so nothing here needs to be defensive about bounds).
 */
export type BlockingEdit =
  | {
      kind: 'prop';
      setId: string;
      propId: string;
      position: Vec3;
      rotationYDeg: number;
      scale: Vec3;
    }
  | {
      kind: 'cast-start';
      segmentKey: string;
      castId: string;
      x: number;
      z: number;
      /** `null` keeps whatever facing the entry already had. */
      yawDeg: number | null;
    }
  | { kind: 'camera-override'; segmentKey: string; override: BlockingCameraOverride | null }
  | { kind: 'shot'; segmentKey: string; shot: BlockingShot };

const round = (value: number) => Math.round(value * 1000) / 1000;
const roundVec = (value: Vec3): Vec3 => [round(value[0]), round(value[1]), round(value[2])];

export function applyEdit(document: BlockingDocument, edit: BlockingEdit): BlockingDocument {
  switch (edit.kind) {
    case 'prop':
      return {
        ...document,
        sets: (document.sets ?? []).map((set) =>
          set.id !== edit.setId
            ? set
            : {
                ...set,
                props: (set.props ?? []).map((prop) =>
                  prop.id !== edit.propId
                    ? prop
                    : {
                        ...prop,
                        position: roundVec(edit.position),
                        rotation_y_deg: round(edit.rotationYDeg),
                        scale: roundVec(edit.scale),
                      },
                ),
              },
        ),
      };
    case 'cast-start':
      return {
        ...document,
        segments: (document.segments ?? []).map((segment) =>
          segment.key !== edit.segmentKey
            ? segment
            : {
                ...segment,
                start: (segment.start ?? []).map((entry) =>
                  entry.cast_id !== edit.castId
                    ? entry
                    : {
                        ...entry,
                        at: { anchor: null, x: round(edit.x), z: round(edit.z) },
                        face:
                          edit.yawDeg === null
                            ? entry.face
                            : { target: null, deg: round(normalizeDeg(edit.yawDeg)) },
                      },
                ),
              },
        ),
      };
    case 'camera-override':
      return {
        ...document,
        segments: (document.segments ?? []).map((segment) =>
          segment.key !== edit.segmentKey
            ? segment
            : { ...segment, camera_override: edit.override ? roundOverride(edit.override) : null },
        ),
      };
    case 'shot':
      // Picking shot grammar hands the camera back to it: a manual camera
      // would otherwise silently keep overriding the preset just chosen.
      return {
        ...document,
        segments: (document.segments ?? []).map((segment) =>
          segment.key !== edit.segmentKey
            ? segment
            : { ...segment, shot: edit.shot, camera_override: null },
        ),
      };
  }
}

export function normalizeDeg(deg: number): number {
  let value = deg % 360;
  if (value > 180) value -= 360;
  if (value <= -180) value += 360;
  return value;
}

function roundOverride(override: BlockingCameraOverride): BlockingCameraOverride {
  const pose = (value: BlockingCameraOverride['start']) => ({
    position: roundVec(value.position as Vec3),
    target: roundVec(value.target as Vec3),
    fov: round(value.fov),
  });
  return { start: pose(override.start), end: override.end ? pose(override.end) : null };
}
