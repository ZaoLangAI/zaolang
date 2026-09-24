import * as THREE from 'three';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';

import { DEG } from '../compiler/math';
import type { BlockingEdit } from '../edits';
import { SELECTION } from '../palette';
import type { BlockingCameraOverride, Vec3 } from '../types';
import type { BlockingPlayer } from './player';

/**
 * The free-view drag editor: click a prop, a mannequin or the director
 * camera to select it, drag the gizmo, and on release emit one
 * `BlockingEdit`. Nothing here writes the document — the studio applies the
 * edit (optimistically) and persists it, and the rebuilt scene comes back
 * through `setDocument`, after which the gizmo re-attaches to the same
 * selection.
 *
 * Mannequin edits move/turn the character's *start mark* in the segment on
 * screen; beats stay as authored. Camera edits write a manual
 * `camera_override` that replaces that segment's shot grammar.
 */

export type EditorSelection =
  | { kind: 'prop'; setId: string; propId: string }
  | { kind: 'cast'; castId: string }
  | { kind: 'camera' }
  | null;

export type GizmoMode = 'translate' | 'rotate' | 'scale';

interface Handlers {
  onEdit: (edit: BlockingEdit) => void;
  onSelect: (selection: EditorSelection) => void;
}

const CLICK_SLOP_PX = 4;

export class BlockingEditor {
  private readonly gizmo: TransformControls;
  private readonly gizmoHelper: THREE.Object3D;
  private readonly raycaster = new THREE.Raycaster();
  private readonly cameraProxy: THREE.Group;
  private readonly proxyGeometry: THREE.BufferGeometry[] = [];
  private readonly proxyMaterial: THREE.MeshBasicMaterial;
  private selection: EditorSelection = null;
  private mode: GizmoMode = 'translate';
  private enabled = false;
  private pointerDown: { x: number; y: number } | null = null;
  private readonly unsubscribe: (() => void)[] = [];

  constructor(
    private readonly player: BlockingPlayer,
    private readonly canvas: HTMLCanvasElement,
    private readonly handlers: Handlers,
  ) {
    this.gizmo = new TransformControls(player.freeCamera, canvas);
    this.gizmo.setSize(0.8);
    this.gizmoHelper = this.gizmo.getHelper();
    this.gizmoHelper.visible = false;
    player.scene.add(this.gizmoHelper);
    this.gizmo.addEventListener('dragging-changed', (event) => {
      const dragging = Boolean((event as unknown as { value: boolean }).value);
      if (player.controls) player.controls.enabled = !dragging && this.enabled;
      if (!dragging) {
        this.commit();
        player.resume();
      }
    });
    this.gizmo.addEventListener('change', () => player.draw());

    // A small camera body + lens cone standing in for the director camera.
    this.proxyMaterial = new THREE.MeshBasicMaterial({ color: SELECTION });
    const body = new THREE.BoxGeometry(0.28, 0.2, 0.34);
    const lens = new THREE.ConeGeometry(0.1, 0.2, 16).rotateX(-Math.PI / 2);
    this.proxyGeometry.push(body, lens);
    this.cameraProxy = new THREE.Group();
    const bodyMesh = new THREE.Mesh(body, this.proxyMaterial);
    const lensMesh = new THREE.Mesh(lens, this.proxyMaterial);
    lensMesh.position.z = -0.25;
    this.cameraProxy.add(bodyMesh, lensMesh);
    this.cameraProxy.traverse((child) => {
      child.userData.camera = true;
    });
    this.cameraProxy.visible = false;
    player.scene.add(this.cameraProxy);

    this.unsubscribe.push(
      player.subscribe((_, frame) => {
        if (!frame || this.isDragging()) return;
        this.cameraProxy.position.set(...frame.camera.position);
        this.cameraProxy.lookAt(new THREE.Vector3(...frame.camera.target));
      }),
      player.onRebuild(() => this.reattach()),
    );
    canvas.addEventListener('pointerdown', this.onPointerDown);
    canvas.addEventListener('pointerup', this.onPointerUp);
  }

  private isDragging(): boolean {
    return this.gizmo.dragging;
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    this.cameraProxy.visible = enabled;
    if (!enabled) this.select(null);
    this.player.draw();
  }

  setMode(mode: GizmoMode): void {
    this.mode = mode;
    this.configureGizmo();
    this.player.draw();
  }

  select(selection: EditorSelection): void {
    this.selection = selection;
    this.reattach();
    this.handlers.onSelect(selection);
  }

  private objectFor(selection: EditorSelection): THREE.Object3D | null {
    if (!selection) return null;
    if (selection.kind === 'camera') return this.cameraProxy;
    if (selection.kind === 'cast') {
      const root = this.player.mannequinRoots().get(selection.castId);
      return root?.visible ? root : null;
    }
    const stage = this.player.stageFor(selection.setId);
    return stage?.group.visible ? (stage.props.get(selection.propId) ?? null) : null;
  }

  private reattach(): void {
    const object = this.enabled ? this.objectFor(this.selection) : null;
    if (object) {
      this.gizmo.attach(object);
      this.gizmoHelper.visible = true;
      this.configureGizmo();
    } else {
      this.gizmo.detach();
      this.gizmoHelper.visible = false;
    }
  }

  private configureGizmo(): void {
    const kind = this.selection?.kind;
    // Cast marks and the camera only move/turn; only props scale.
    const mode: GizmoMode =
      kind === 'camera'
        ? 'translate'
        : kind === 'cast' && this.mode === 'scale'
          ? 'translate'
          : this.mode;
    this.gizmo.setMode(mode);
    this.gizmo.setSpace(mode === 'translate' ? 'world' : 'local');
    // Turning is always about the vertical axis; a cast mark stays on the
    // floor, while props and the camera may also move up and down.
    this.gizmo.showX = mode !== 'rotate';
    this.gizmo.showZ = mode !== 'rotate';
    this.gizmo.showY = mode === 'rotate' || kind !== 'cast';
  }

  private onPointerDown = (event: PointerEvent) => {
    this.pointerDown = { x: event.clientX, y: event.clientY };
  };

  private onPointerUp = (event: PointerEvent) => {
    const start = this.pointerDown;
    this.pointerDown = null;
    if (!this.enabled || !start || this.isDragging() || this.gizmo.axis !== null) return;
    // A drag that orbited the view is not a click.
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > CLICK_SLOP_PX) return;
    this.select(this.pick(event));
  };

  private pick(event: PointerEvent): EditorSelection {
    const rect = this.canvas.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(pointer, this.player.freeCamera);
    const candidates: THREE.Object3D[] = [this.cameraProxy];
    for (const root of this.player.mannequinRoots().values())
      if (root.visible) candidates.push(root);
    const setId = this.player.lastFrame?.segment.set.id;
    const stage = setId ? this.player.stageFor(setId) : undefined;
    if (stage && setId) candidates.push(...stage.props.values());
    for (const hit of this.raycaster.intersectObjects(candidates, true)) {
      let node: THREE.Object3D | null = hit.object;
      while (node) {
        if (node.userData.camera) return { kind: 'camera' };
        if (typeof node.userData.castId === 'string')
          return { kind: 'cast', castId: node.userData.castId };
        if (typeof node.userData.propId === 'string' && setId) {
          return { kind: 'prop', setId, propId: node.userData.propId };
        }
        node = node.parent;
      }
    }
    return null;
  }

  private commit(): void {
    const selection = this.selection;
    const object = this.objectFor(selection);
    const frame = this.player.lastFrame;
    const document = this.player.document;
    if (!selection || !object || !frame || !document) return;

    if (selection.kind === 'prop') {
      const prop = document.sets
        ?.find((set) => set.id === selection.setId)
        ?.props?.find((item) => item.id === selection.propId);
      if (!prop) return;
      const [sx, sy, sz] = prop.scale;
      this.handlers.onEdit({
        kind: 'prop',
        setId: selection.setId,
        propId: selection.propId,
        position: [object.position.x, Math.max(0, object.position.y), object.position.z],
        rotationYDeg: object.rotation.y / DEG,
        scale: [(sx ?? 1) * object.scale.x, (sy ?? 1) * object.scale.y, (sz ?? 1) * object.scale.z],
      });
      return;
    }
    if (selection.kind === 'cast') {
      this.handlers.onEdit({
        kind: 'cast-start',
        segmentKey: frame.segment.key,
        castId: selection.castId,
        x: object.position.x,
        z: object.position.z,
        yawDeg: this.mode === 'rotate' ? object.rotation.y / DEG : null,
      });
      return;
    }
    const override: BlockingCameraOverride = {
      start: {
        position: object.position.toArray() as Vec3,
        target: frame.camera.target,
        fov: frame.camera.fov,
      },
      end: null,
    };
    this.handlers.onEdit({ kind: 'camera-override', segmentKey: frame.segment.key, override });
  }

  /** "Use this view as the camera": the free view's pose becomes a manual
   * camera for the segment on screen. */
  captureFreeView(): BlockingEdit | null {
    const frame = this.player.lastFrame;
    const target = this.player.controls?.target;
    if (!frame || !target) return null;
    return {
      kind: 'camera-override',
      segmentKey: frame.segment.key,
      override: {
        start: {
          position: this.player.freeCamera.position.toArray() as Vec3,
          target: target.toArray() as Vec3,
          fov: frame.camera.fov,
        },
        end: null,
      },
    };
  }

  dispose(): void {
    this.canvas.removeEventListener('pointerdown', this.onPointerDown);
    this.canvas.removeEventListener('pointerup', this.onPointerUp);
    this.unsubscribe.forEach((stop) => stop());
    this.gizmo.detach();
    this.gizmo.dispose();
    this.player.scene.remove(this.gizmoHelper, this.cameraProxy);
    this.proxyGeometry.forEach((geometry) => geometry.dispose());
    this.proxyMaterial.dispose();
  }
}
