import * as THREE from 'three';

import { DEG } from '../compiler/math';
import { ANCHOR_MARK, GRID_MAJOR, GRID_MINOR, GROUND_COLORS, PROP_COLORS } from '../palette';
import type { BlockingProp, BlockingSet, Primitive } from '../types';

/**
 * One set (a script scene) as a three.js group: a ground slab sized to the
 * set, a metre grid, the props built from primitives, and anchor marks.
 *
 * Prop convention (shared with the `blocking_derive` prompt): `position` is
 * the centre of the prop's *footprint* with y = the height of its underside
 * (0 = standing on the floor); `scale` is its bounding size in metres.
 * `plane` is a thin upright panel (wall, door, window, screen).
 *
 * Every mesh records its prop id in `userData.propId` so the drag editor can
 * map a picked mesh back to the document.
 */

export interface StageGroup {
  group: THREE.Group;
  /** Grid + anchor marks: shown while authoring, hidden in exports. */
  guides: THREE.Group;
  props: Map<string, THREE.Object3D>;
  dispose: () => void;
}

const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1);

function primitiveGeometry(primitive: Primitive): THREE.BufferGeometry {
  switch (primitive) {
    case 'box':
      return UNIT_BOX;
    case 'plane':
      return new THREE.BoxGeometry(1, 1, 0.04);
    case 'cylinder':
      return new THREE.CylinderGeometry(0.5, 0.5, 1, 24);
    case 'sphere':
      return new THREE.SphereGeometry(0.5, 24, 16);
    case 'cone':
      return new THREE.ConeGeometry(0.5, 1, 24);
    case 'capsule':
      return new THREE.CapsuleGeometry(0.25, 0.5, 4, 16);
    case 'torus':
      return new THREE.TorusGeometry(0.4, 0.1, 12, 32).rotateX(Math.PI / 2);
    case 'stairs':
      return UNIT_BOX;
  }
}

function buildStairs(material: THREE.Material): THREE.Group {
  // Unit-size flight rising toward -z; the prop's scale stretches it. Step
  // count follows the unit box, so a 1m-high flight has ~6 risers.
  const group = new THREE.Group();
  const steps = 6;
  for (let i = 0; i < steps; i += 1) {
    const step = new THREE.Mesh(UNIT_BOX, material);
    const height = (i + 1) / steps;
    step.scale.set(1, height, 1 / steps);
    step.position.set(0, height / 2 - 0.5, 0.5 - (i + 0.5) / steps);
    step.castShadow = true;
    step.receiveShadow = true;
    group.add(step);
  }
  return group;
}

export function buildProp(
  prop: BlockingProp,
  materials: Map<string, THREE.Material>,
): THREE.Object3D {
  const key = prop.color_role;
  let material = materials.get(key);
  if (!material) {
    material = new THREE.MeshStandardMaterial({
      color: PROP_COLORS[prop.color_role],
      roughness: 0.92,
      metalness: 0,
    });
    materials.set(key, material);
  }

  // Outer group carries the document transform (footprint centre, yaw);
  // the inner object is the unit primitive scaled and lifted so its
  // underside sits at `position.y`.
  const holder = new THREE.Group();
  const [x, y, z] = prop.position;
  holder.position.set(x ?? 0, y ?? 0, z ?? 0);
  holder.rotation.y = prop.rotation_y_deg * DEG;
  const [sx, sy, sz] = prop.scale;

  const inner: THREE.Object3D =
    prop.primitive === 'stairs'
      ? buildStairs(material)
      : new THREE.Mesh(primitiveGeometry(prop.primitive), material);
  inner.scale.set(sx ?? 1, sy ?? 1, prop.primitive === 'plane' ? 1 : (sz ?? 1));
  inner.position.y = (sy ?? 1) / 2;
  if (inner instanceof THREE.Mesh) {
    inner.castShadow = true;
    inner.receiveShadow = true;
  }
  holder.add(inner);
  holder.userData.propId = prop.id;
  holder.traverse((child) => {
    child.userData.propId = prop.id;
  });
  return holder;
}

export function buildStage(set: BlockingSet): StageGroup {
  const group = new THREE.Group();
  group.name = `set:${set.id}`;
  const guides = new THREE.Group();
  guides.name = 'guides';
  const owned: { dispose: () => void }[] = [];
  const materials = new Map<string, THREE.Material>();

  const groundMaterial = new THREE.MeshStandardMaterial({
    color: GROUND_COLORS[set.ground],
    roughness: 1,
    metalness: 0,
  });
  const groundGeometry = new THREE.PlaneGeometry(set.width_m, set.depth_m);
  const ground = new THREE.Mesh(groundGeometry, groundMaterial);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  ground.name = 'ground';
  group.add(ground);
  owned.push(groundGeometry, groundMaterial);

  // A wider, slightly darker apron so the set does not end at a hard edge
  // when a wide lens looks past it.
  const apronMaterial = new THREE.MeshStandardMaterial({
    color: new THREE.Color(GROUND_COLORS[set.ground]).multiplyScalar(0.9),
    roughness: 1,
  });
  const apronGeometry = new THREE.PlaneGeometry(set.width_m * 6, set.depth_m * 6);
  const apron = new THREE.Mesh(apronGeometry, apronMaterial);
  apron.rotation.x = -Math.PI / 2;
  apron.position.y = -0.005;
  apron.receiveShadow = true;
  group.add(apron);
  owned.push(apronGeometry, apronMaterial);

  const gridSize = Math.max(set.width_m, set.depth_m);
  const grid = new THREE.GridHelper(gridSize, Math.round(gridSize), GRID_MAJOR, GRID_MINOR);
  grid.position.y = 0.002;
  (grid.material as THREE.Material).transparent = true;
  (grid.material as THREE.Material).opacity = 0.45;
  guides.add(grid);
  owned.push(grid.geometry, grid.material as THREE.Material);

  const anchorGeometry = new THREE.RingGeometry(0.16, 0.22, 24).rotateX(-Math.PI / 2);
  const anchorMaterial = new THREE.MeshBasicMaterial({
    color: ANCHOR_MARK,
    transparent: true,
    opacity: 0.8,
  });
  owned.push(anchorGeometry, anchorMaterial);
  for (const anchor of set.anchors ?? []) {
    const mark = new THREE.Mesh(anchorGeometry, anchorMaterial);
    mark.position.set(anchor.x, 0.004, anchor.z);
    mark.userData.anchorId = anchor.id;
    mark.userData.anchorLabel = anchor.label;
    guides.add(mark);
  }
  group.add(guides);

  const props = new Map<string, THREE.Object3D>();
  for (const prop of set.props ?? []) {
    const object = buildProp(prop, materials);
    props.set(prop.id, object);
    group.add(object);
  }

  return {
    group,
    guides,
    props,
    dispose: () => {
      owned.forEach((item) => item.dispose());
      materials.forEach((material) => material.dispose());
      group.traverse((child) => {
        if (child instanceof THREE.Mesh && child.geometry !== UNIT_BOX) {
          const geometry = child.geometry as THREE.BufferGeometry;
          if (!owned.includes(geometry)) geometry.dispose();
        }
      });
    },
  };
}
