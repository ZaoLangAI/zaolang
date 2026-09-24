import * as THREE from 'three';

import { DEG } from '../compiler/math';
import { JOINTS, type JointName, type Pose } from './poses';

/**
 * A low-poly FK mannequin built from primitives (capsules, spheres, boxes),
 * sized for 1.7m and scaled per character. The root sits on the floor at
 * the character's mark and yaws about +Y; every limb is its own joint group
 * so `applyPose` is just "copy these Euler angles".
 *
 * Local +z is the mannequin's front; a darker nose and toe caps make facing
 * readable at a glance — which is exactly what a video model needs to copy
 * from the reference clip.
 */

const STANDING_HIPS_Y = 0.93;

export interface Mannequin {
  root: THREE.Group;
  /** Attachment point above the head (for the name tag). */
  crown: THREE.Object3D;
  applyPose: (pose: Pose) => void;
  setHighlight: (on: boolean) => void;
  dispose: () => void;
}

export function createMannequin(options: {
  color: number;
  height: number;
  castShadow?: boolean;
}): Mannequin {
  const scale = options.height / 1.7;
  const geometries: THREE.BufferGeometry[] = [];
  const skin = new THREE.MeshStandardMaterial({
    color: options.color,
    roughness: 0.65,
    metalness: 0.05,
  });
  const trim = new THREE.MeshStandardMaterial({
    color: new THREE.Color(options.color).multiplyScalar(0.55),
    roughness: 0.8,
  });
  const materials = [skin, trim];

  const mesh = (geometry: THREE.BufferGeometry, material = skin) => {
    geometries.push(geometry);
    const result = new THREE.Mesh(geometry, material);
    result.castShadow = options.castShadow ?? true;
    result.receiveShadow = false;
    return result;
  };
  const capsule = (radius: number, length: number, material = skin) =>
    mesh(new THREE.CapsuleGeometry(radius, length, 4, 10), material);

  const root = new THREE.Group();
  root.name = 'mannequin';
  const body = new THREE.Group();
  body.scale.setScalar(scale);
  root.add(body);

  const joints = {} as Record<JointName, THREE.Group>;
  const joint = (name: JointName, parent: THREE.Object3D, x: number, y: number, z = 0) => {
    const group = new THREE.Group();
    group.name = name;
    group.position.set(x, y, z);
    parent.add(group);
    joints[name] = group;
    return group;
  };

  const hips = new THREE.Group();
  hips.position.y = STANDING_HIPS_Y;
  body.add(hips);
  const pelvis = mesh(new THREE.SphereGeometry(0.15, 16, 12));
  pelvis.scale.set(1.05, 0.62, 0.72);
  hips.add(pelvis);

  const spine = joint('spine', hips, 0, 0.06);
  const waist = capsule(0.115, 0.14);
  waist.position.y = 0.1;
  spine.add(waist);
  const chest = joint('chest', spine, 0, 0.2);
  const torso = mesh(new THREE.SphereGeometry(0.19, 18, 14));
  torso.scale.set(1.0, 0.9, 0.62);
  torso.position.y = 0.1;
  chest.add(torso);

  const neck = joint('neck', chest, 0, 0.25);
  const neckMesh = capsule(0.045, 0.05);
  neckMesh.position.y = 0.03;
  neck.add(neckMesh);
  const head = joint('head', neck, 0, 0.08);
  const skull = mesh(new THREE.SphereGeometry(0.11, 20, 16));
  skull.scale.set(0.92, 1.1, 1.0);
  skull.position.y = 0.1;
  head.add(skull);
  const nose = mesh(new THREE.BoxGeometry(0.05, 0.035, 0.05), trim);
  nose.position.set(0, 0.1, 0.105);
  head.add(nose);

  const crown = new THREE.Object3D();
  crown.position.y = 0.34;
  head.add(crown);

  for (const side of ['l', 'r'] as const) {
    const sign = side === 'l' ? 1 : -1;
    const shoulder = joint(`${side}Shoulder`, chest, 0.19 * sign, 0.2);
    const upper = capsule(0.045, 0.2);
    upper.position.y = -0.14;
    shoulder.add(upper);
    const elbow = joint(`${side}Elbow`, shoulder, 0, -0.28);
    const lower = capsule(0.04, 0.18);
    lower.position.y = -0.13;
    elbow.add(lower);
    const hand = mesh(new THREE.SphereGeometry(0.048, 10, 8), trim);
    hand.position.y = -0.27;
    elbow.add(hand);

    const hip = joint(`${side}Hip`, hips, 0.09 * sign, -0.04);
    const thigh = capsule(0.068, 0.3);
    thigh.position.y = -0.21;
    hip.add(thigh);
    const knee = joint(`${side}Knee`, hip, 0, -0.43);
    const shin = capsule(0.052, 0.32);
    shin.position.y = -0.21;
    knee.add(shin);
    const foot = mesh(new THREE.BoxGeometry(0.09, 0.06, 0.22), trim);
    foot.position.set(0, -0.44, 0.05);
    knee.add(foot);
  }

  const applyPose = (pose: Pose) => {
    hips.position.y = STANDING_HIPS_Y - pose.hipsDrop;
    hips.rotation.set(pose.bodyPitch * DEG, 0, 0);
    for (const name of JOINTS) {
      const [x, y, z] = pose.joints[name];
      joints[name].rotation.set(x * DEG, y * DEG, z * DEG);
    }
  };

  const setHighlight = (on: boolean) => {
    skin.emissive.setHex(on ? 0x331a10 : 0x000000);
  };

  return {
    root,
    crown,
    applyPose,
    setHighlight,
    dispose: () => {
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
    },
  };
}
