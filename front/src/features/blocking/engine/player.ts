import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';

import { compileBlocking, type FrameState, type Timeline } from '../compiler/compile';
import { ASPECT_WIDTH_OVER_HEIGHT } from '../compiler/camera';
import { DEG } from '../compiler/math';
import { STUDIO_BACKGROUND, castColor } from '../palette';
import type { BlockingDocument, CameraPose } from '../types';
import { createMannequin, type Mannequin } from './mannequin';
import { poseFor } from './poses';
import { buildStage, type StageGroup } from './stage';

/**
 * The 白膜 player: owns one WebGL renderer, builds the scene from a blocking
 * document, and renders any episode time through the compiled timeline.
 *
 * Two uses share this class so they cannot drift apart:
 * - the studio viewport (`interactive: true`): play/pause, a free orbit view
 *   with the director camera drawn as a frustum, name/image tags as DOM
 *   labels over each mannequin;
 * - the exporter (`interactive: false`, often on an `OffscreenCanvas`):
 *   no controls, no guides, no labels — just `renderAt(t)` frame by frame.
 */

export type ViewMode = 'director' | 'free';

export interface PlayerOptions {
  canvas: HTMLCanvasElement | OffscreenCanvas;
  interactive: boolean;
  /** DOM layer for name/image tags; omit to render without labels. */
  labelLayer?: HTMLElement;
  pixelRatio?: number;
  shadows?: boolean;
}

export interface CastLabel {
  name: string;
  colorCss: string;
  imageUrl: string | null;
}

type TimeListener = (time: number, frame: FrameState | null) => void;

const FREE_VIEW_DISTANCE = 9;

export class BlockingPlayer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly directorCamera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 400);
  readonly freeCamera = new THREE.PerspectiveCamera(50, 16 / 9, 0.05, 400);
  timeline: Timeline | null = null;
  document: BlockingDocument | null = null;

  private readonly interactive: boolean;
  private readonly labelRenderer: CSS2DRenderer | null = null;
  /** Free-view orbit; the drag editor disables it while a gizmo is held. */
  readonly controls: OrbitControls | null = null;
  private readonly cameraHelper: THREE.CameraHelper;
  private stages = new Map<string, StageGroup>();
  private mannequins = new Map<string, { mannequin: Mannequin; label: CSS2DObject | null }>();
  private labels: Record<string, CastLabel> = {};
  private activeSetId: string | null = null;
  private listeners = new Set<TimeListener>();
  private rebuildListeners = new Set<() => void>();
  private frameHandle = 0;
  private lastTick = 0;
  private width = 1;
  private height = 1;
  private showGuides: boolean;
  private showLabels: boolean;
  private disposed = false;

  time = 0;
  playing = false;
  view: ViewMode = 'director';
  lastFrame: FrameState | null = null;

  constructor(options: PlayerOptions) {
    this.interactive = options.interactive;
    this.showGuides = options.interactive;
    this.showLabels = Boolean(options.labelLayer);
    this.renderer = new THREE.WebGLRenderer({
      canvas: options.canvas,
      antialias: true,
      alpha: false,
      // Exports read pixels back after every frame.
      preserveDrawingBuffer: !options.interactive,
    });
    this.renderer.setPixelRatio(options.pixelRatio ?? 1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = options.shadows ?? true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene.background = new THREE.Color(STUDIO_BACKGROUND);
    this.scene.fog = new THREE.Fog(STUDIO_BACKGROUND, 30, 120);
    const hemisphere = new THREE.HemisphereLight(0xffffff, 0x8a9096, 1.35);
    this.scene.add(hemisphere);
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(6, 12, 8);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -20;
    sun.shadow.camera.right = 20;
    sun.shadow.camera.top = 20;
    sun.shadow.camera.bottom = -20;
    sun.shadow.bias = -0.0005;
    this.scene.add(sun);

    this.cameraHelper = new THREE.CameraHelper(this.directorCamera);
    this.cameraHelper.visible = false;
    this.scene.add(this.cameraHelper);

    if (options.labelLayer) {
      this.labelRenderer = new CSS2DRenderer({ element: options.labelLayer });
    }
    if (options.interactive && options.canvas instanceof HTMLCanvasElement) {
      this.controls = new OrbitControls(this.freeCamera, options.canvas);
      this.controls.enableDamping = true;
      this.controls.enabled = false;
      this.controls.addEventListener('change', () => this.requestRender());
    }
  }

  // ------------------------------------------------------------------ setup

  setDocument(document: BlockingDocument, labels: Record<string, CastLabel> = {}): void {
    this.document = document;
    this.labels = labels;
    this.timeline = compileBlocking(document);
    this.rebuildScene();
    this.time = Math.min(this.time, this.timeline.duration);
    this.renderAt(this.time);
    for (const listener of this.rebuildListeners) listener();
  }

  private rebuildScene(): void {
    for (const stage of this.stages.values()) {
      this.scene.remove(stage.group);
      stage.dispose();
    }
    this.stages.clear();
    for (const { mannequin, label } of this.mannequins.values()) {
      this.scene.remove(mannequin.root);
      label?.element.remove();
      mannequin.dispose();
    }
    this.mannequins.clear();
    this.activeSetId = null;
    const document = this.document;
    if (!document) return;

    for (const set of document.sets ?? []) {
      const stage = buildStage(set);
      stage.group.visible = false;
      stage.guides.visible = this.showGuides;
      this.stages.set(set.id, stage);
      this.scene.add(stage.group);
    }
    for (const member of document.cast ?? []) {
      const mannequin = createMannequin({
        color: castColor(member.color_index).hex,
        height: member.height_m,
      });
      mannequin.root.visible = false;
      mannequin.root.traverse((child) => {
        child.userData.castId = member.id;
      });
      this.scene.add(mannequin.root);
      let label: CSS2DObject | null = null;
      if (this.labelRenderer) {
        label = new CSS2DObject(this.labelElement(member.id, member.name, member.color_index));
        mannequin.crown.add(label);
        label.visible = this.showLabels;
      }
      this.mannequins.set(member.id, { mannequin, label });
    }
  }

  private labelElement(castId: string, name: string, colorIndex: number): HTMLElement {
    const info = this.labels[castId];
    // Plain DOM (CSS2DRenderer), not a WebGL texture: a character image
    // from the asset bucket never has to be CORS-readable, and labels can
    // never leak into an exported frame.
    const element = document.createElement('div');
    element.className =
      'pointer-events-none flex items-center gap-1.5 whitespace-nowrap rounded-full border-2 bg-surface/90 py-0.5 pl-0.5 pr-2 text-[11px] font-medium text-text shadow-card';
    element.style.borderColor = info?.colorCss ?? castColor(colorIndex).css;
    if (info?.imageUrl) {
      const image = document.createElement('img');
      image.src = info.imageUrl;
      image.alt = '';
      image.decoding = 'async';
      image.className = 'size-7 rounded-full object-cover';
      element.appendChild(image);
    } else {
      const dot = document.createElement('span');
      dot.className = 'ml-1 size-2.5 rounded-full';
      dot.style.backgroundColor = info?.colorCss ?? castColor(colorIndex).css;
      element.appendChild(dot);
    }
    const text = document.createElement('span');
    text.textContent = info?.name ?? name;
    element.appendChild(text);
    return element;
  }

  setSize(width: number, height: number): void {
    this.width = Math.max(1, Math.floor(width));
    this.height = Math.max(1, Math.floor(height));
    this.renderer.setSize(this.width, this.height, false);
    this.labelRenderer?.setSize(this.width, this.height);
    this.freeCamera.aspect = this.width / this.height;
    this.freeCamera.updateProjectionMatrix();
    this.requestRender();
  }

  setView(view: ViewMode): void {
    if (view === this.view) return;
    this.view = view;
    if (view === 'free') {
      // Start the orbit from where the director camera is, pulled back a
      // little so its frustum is visible.
      const pose = this.lastFrame?.camera;
      const target = pose ? new THREE.Vector3(...pose.target) : new THREE.Vector3(0, 1, 0);
      const from = pose
        ? new THREE.Vector3(...pose.position).sub(target).setLength(FREE_VIEW_DISTANCE)
        : new THREE.Vector3(6, 5, 8);
      this.freeCamera.position.copy(target.clone().add(from).add(new THREE.Vector3(0, 2.5, 0)));
      this.controls?.target.copy(target);
      this.controls?.update();
    }
    if (this.controls) this.controls.enabled = view === 'free';
    this.cameraHelper.visible = view === 'free';
    this.resume();
  }

  setGuides(visible: boolean): void {
    this.showGuides = visible;
    for (const stage of this.stages.values()) stage.guides.visible = visible;
    this.requestRender();
  }

  setLabels(visible: boolean): void {
    this.showLabels = visible;
    for (const { label } of this.mannequins.values()) if (label) label.visible = visible;
    this.requestRender();
  }

  // --------------------------------------------------------------- playback

  subscribe(listener: TimeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Called after every scene rebuild (a new document) — the drag editor
   * re-attaches its gizmo to the rebuilt object. */
  onRebuild(listener: () => void): () => void {
    this.rebuildListeners.add(listener);
    return () => this.rebuildListeners.delete(listener);
  }

  play(): void {
    if (!this.timeline || this.timeline.duration <= 0) return;
    if (this.time >= this.timeline.duration - 1e-3) this.time = 0;
    this.playing = true;
    this.lastTick = performance.now();
    this.loop();
  }

  pause(): void {
    this.playing = false;
    this.emit();
  }

  seek(time: number): void {
    const duration = this.timeline?.duration ?? 0;
    this.time = Math.min(Math.max(time, 0), duration);
    this.renderAt(this.time);
  }

  /** (Re)starts the frame loop — it runs while playing or while the free
   * view's orbit is live, and stops on its own otherwise. */
  resume(): void {
    this.lastTick = performance.now();
    this.loop();
  }

  private loop = (): void => {
    if (this.disposed) return;
    cancelAnimationFrame(this.frameHandle);
    const now = performance.now();
    if (this.playing && this.timeline) {
      this.time += (now - this.lastTick) / 1000;
      if (this.time >= this.timeline.duration) {
        this.time = this.timeline.duration;
        this.playing = false;
      }
    }
    this.lastTick = now;
    this.controls?.update();
    // Paused, only redraw: re-applying the frame would snap a prop or
    // mannequin the drag editor is holding back to its document position.
    if (this.playing) this.renderAt(this.time);
    else this.draw();
    if (this.playing || this.controls?.enabled) {
      this.frameHandle = requestAnimationFrame(this.loop);
    }
  };

  private renderQueued = false;

  requestRender(): void {
    if (this.playing || this.renderQueued || this.disposed) return;
    this.renderQueued = true;
    requestAnimationFrame(() => {
      this.renderQueued = false;
      this.controls?.update();
      this.draw();
    });
  }

  private emit(): void {
    for (const listener of this.listeners) listener(this.time, this.lastFrame);
  }

  // -------------------------------------------------------------- rendering

  /** Pose everything for episode time `time` and draw one frame. */
  renderAt(time: number): FrameState | null {
    const frame = this.timeline?.sample(time) ?? null;
    this.lastFrame = frame;
    this.applyFrame(frame);
    this.draw();
    this.emit();
    return frame;
  }

  applyFrame(frame: FrameState | null): void {
    const setId = frame?.segment.set.id ?? null;
    if (setId !== this.activeSetId) {
      for (const [id, stage] of this.stages) stage.group.visible = id === setId;
      this.activeSetId = setId;
    }
    const onSet = new Set(frame?.cast.map((cast) => cast.id) ?? []);
    for (const [id, { mannequin }] of this.mannequins) {
      mannequin.root.visible = onSet.has(id);
    }
    if (!frame) return;
    for (const cast of frame.cast) {
      const entry = this.mannequins.get(cast.id);
      if (!entry) continue;
      const root = entry.mannequin.root;
      root.position.set(cast.position[0], cast.position[1], cast.position[2]);
      root.rotation.y = cast.yaw * DEG;
      entry.mannequin.applyPose(poseFor(cast, frame.localTime, cast.member.height_m / 1.7));
    }
    this.applyCamera(frame.camera);
  }

  private applyCamera(pose: CameraPose): void {
    const aspect = this.timeline ? ASPECT_WIDTH_OVER_HEIGHT[this.timeline.aspect] : 16 / 9;
    const camera = this.directorCamera;
    camera.position.set(...pose.position);
    camera.fov = pose.fov;
    camera.aspect = aspect;
    camera.up.set(0, 1, 0);
    camera.lookAt(new THREE.Vector3(...pose.target));
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
    this.cameraHelper.update();
  }

  draw(): void {
    if (this.disposed) return;
    const camera = this.view === 'free' ? this.freeCamera : this.directorCamera;
    this.renderer.render(this.scene, camera);
    if (this.labelRenderer && this.showLabels) this.labelRenderer.render(this.scene, camera);
  }

  /** The director camera's current pose — what the drag editor writes into
   * a `camera_override`. */
  currentCameraPose(): CameraPose | null {
    return this.lastFrame?.camera ?? null;
  }

  mannequinRoots(): Map<string, THREE.Object3D> {
    return new Map([...this.mannequins].map(([id, entry]) => [id, entry.mannequin.root]));
  }

  stageFor(setId: string): StageGroup | undefined {
    return this.stages.get(setId);
  }

  get domElement(): HTMLCanvasElement | OffscreenCanvas {
    return this.renderer.domElement;
  }

  dispose(): void {
    this.disposed = true;
    this.playing = false;
    cancelAnimationFrame(this.frameHandle);
    this.controls?.dispose();
    this.document = null;
    this.rebuildScene();
    this.cameraHelper.dispose();
    this.listeners.clear();
    this.rebuildListeners.clear();
    this.renderer.dispose();
    // Hand the WebGL context back immediately — browsers cap live contexts,
    // same reasoning as `features/canvas/panorama-viewer.tsx`.
    this.renderer.forceContextLoss();
  }
}
