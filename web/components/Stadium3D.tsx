"use client";

import { useEffect, useRef, useState } from "react";
import type { Frame } from "@/lib/types";

/**
 * 3D stadium view: animated human players driven by the live tracking feed.
 * Pitch coords (x 0..105, y 0..68 metres) → world (X = x - 52.5, Z = y - 34, Y up).
 */

export interface Stadium3DProps {
  frame: Frame | null;
  ids: (string | null)[];
  players: Record<string, { name: string; number: number; short_name?: string; short?: string }>;
  homeColor: string;
  awayColor: string;
  focusId?: string | null;
  height?: number | string;
  initialCam?: CamMode;
  showControls?: boolean;
  celebrate?: { side: "home" | "away"; at: number } | null;
  /** Live event feed (passes, shots, …) — drives real kicks and ball flight. */
  events?: any[];
  /** Replay speed multiplier, to convert event durations to real time. */
  speed?: number;
}

type CamMode = "broadcast" | "tactical" | "follow";

const PITCH_L = 105;
const PITCH_W = 68;

// ------------------------------------------------------------------ procedural textures

function grassCanvas(): HTMLCanvasElement {
  const ppm = 28; // pixels per metre
  const margin = 6; // metres of run-off around the pitch
  const W = Math.round((PITCH_L + margin * 2) * ppm);
  const H = Math.round((PITCH_W + margin * 2) * ppm);
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const g = c.getContext("2d")!;
  // Mowing stripes (along the length), slightly different shades.
  const stripes = 20;
  const sw = (PITCH_L + margin * 2) / stripes;
  for (let i = 0; i < stripes; i++) {
    g.fillStyle = i % 2 ? "#2f5f2a" : "#386b31";
    g.fillRect(Math.round(i * sw * ppm), 0, Math.ceil(sw * ppm) + 1, H);
  }
  // Fine grain noise for blades of grass.
  const img = g.getImageData(0, 0, W, H);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * 22;
    d[i] = Math.max(0, Math.min(255, d[i] + n * 0.6));
    d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + n));
    d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + n * 0.5));
  }
  g.putImageData(img, 0, 0);
  // Subtle wear patches in the goalmouths and centre circle.
  const wear = (x: number, y: number, r: number) => {
    const grd = g.createRadialGradient(x * ppm, y * ppm, 0, x * ppm, y * ppm, r * ppm);
    grd.addColorStop(0, "rgba(120,110,70,0.35)");
    grd.addColorStop(1, "rgba(120,110,70,0)");
    g.fillStyle = grd;
    g.beginPath();
    g.arc(x * ppm, y * ppm, r * ppm, 0, Math.PI * 2);
    g.fill();
  };
  wear(margin + 5, margin + 34, 6);
  wear(margin + 100, margin + 34, 6);
  wear(margin + 52.5, margin + 34, 4);
  // Markings.
  const X = (x: number) => (x + margin) * ppm;
  const Y = (y: number) => (y + margin) * ppm;
  g.strokeStyle = "rgba(245,245,240,0.92)";
  g.lineWidth = 0.12 * ppm;
  g.strokeRect(X(0), Y(0), PITCH_L * ppm, PITCH_W * ppm);
  g.beginPath(); g.moveTo(X(52.5), Y(0)); g.lineTo(X(52.5), Y(68)); g.stroke();
  g.beginPath(); g.arc(X(52.5), Y(34), 9.15 * ppm, 0, Math.PI * 2); g.stroke();
  const spot = (x: number, y: number) => { g.beginPath(); g.arc(X(x), Y(y), 0.22 * ppm, 0, Math.PI * 2); g.fillStyle = "rgba(245,245,240,0.92)"; g.fill(); };
  spot(52.5, 34); spot(11, 34); spot(94, 34);
  g.strokeRect(X(0), Y(13.84), 16.5 * ppm, 40.32 * ppm);
  g.strokeRect(X(88.5), Y(13.84), 16.5 * ppm, 40.32 * ppm);
  g.strokeRect(X(0), Y(24.84), 5.5 * ppm, 18.32 * ppm);
  g.strokeRect(X(99.5), Y(24.84), 5.5 * ppm, 18.32 * ppm);
  const arcAngle = Math.acos(5.5 / 9.15);
  g.beginPath(); g.arc(X(11), Y(34), 9.15 * ppm, -arcAngle, arcAngle); g.stroke();
  g.beginPath(); g.arc(X(94), Y(34), 9.15 * ppm, Math.PI - arcAngle, Math.PI + arcAngle); g.stroke();
  for (const [cx, cy, a0] of [[0, 0, 0], [105, 0, Math.PI / 2], [105, 68, Math.PI], [0, 68, -Math.PI / 2]] as const) {
    g.beginPath(); g.arc(X(cx), Y(cy), 1 * ppm, a0, a0 + Math.PI / 2); g.stroke();
  }
  return c;
}

function crowdCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 256;
  const g = c.getContext("2d")!;
  g.fillStyle = "#14181d";
  g.fillRect(0, 0, c.width, c.height);
  const palette = ["#d9d4c7", "#1f4fd1", "#2b5ee8", "#e4572e", "#f2f2f2", "#3a3f47", "#c2b59b", "#8a8f99", "#1b1f24", "#e8c39e"];
  for (let row = 0; row < 32; row++) {
    for (let col = 0; col < 160; col++) {
      if (Math.random() < 0.08) continue;
      g.fillStyle = palette[(Math.random() * palette.length) | 0];
      const x = col * 6.4 + Math.random() * 2;
      const y = row * 8 + Math.random() * 2;
      g.fillRect(x, y, 3.6, 5.2);
      g.fillStyle = "#e8c39e";
      g.fillRect(x + 0.6, y - 2, 2.4, 2.2);
    }
  }
  return c;
}

// Fictional sponsors (Microsoft's sample brands). Override with NEXT_PUBLIC_SPONSORS="A,B,C".
const SPONSORS = ((typeof process !== "undefined" && process.env.NEXT_PUBLIC_SPONSORS) ||
  "TOUCHLINE,CONTOSO BANK,NORTHWIND AIR,FABRIKAM,ADVENTURE WORKS,TAILSPIN TOYS,WIDE WORLD IMPORTERS,LIVE · EXPLAINED").split(",");

function boardCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 4096;
  c.height = 64;
  const g = c.getContext("2d")!;
  const n = SPONSORS.length;
  const w = c.width / n;
  const bgs = ["#0f1412", "#0e6b47", "#123b7a", "#1b1f24", "#7a1f12", "#0f1412", "#3d1a5c", "#0e6b47"];
  const fgs = ["#f2a900", "#f5f3ee", "#ffffff", "#36c2ff", "#ffd8a8", "#f5f3ee", "#e0c3ff", "#f2a900"];
  SPONSORS.forEach((name, i) => {
    g.fillStyle = bgs[i % bgs.length];
    g.fillRect(i * w, 0, w, 64);
    g.fillStyle = fgs[i % fgs.length];
    g.font = "bold 40px Arial Narrow, Arial, sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(name.trim().toUpperCase(), i * w + w / 2, 34);
  });
  return c;
}

function ballCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 128;
  const g = c.getContext("2d")!;
  g.fillStyle = "#f7f7f5";
  g.fillRect(0, 0, 256, 128);
  g.fillStyle = "#1b1f24";
  for (let i = 0; i < 12; i++) {
    const x = (i % 6) * 44 + (i >= 6 ? 22 : 0) + 10;
    const y = i >= 6 ? 88 : 36;
    g.beginPath();
    for (let k = 0; k < 5; k++) {
      const a = (k / 5) * Math.PI * 2 - Math.PI / 2;
      g.lineTo(x + Math.cos(a) * 11, y + Math.sin(a) * 11);
    }
    g.fill();
  }
  return c;
}

function labelCanvas(text: string, color: string): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 96;
  const g = c.getContext("2d")!;
  g.fillStyle = "rgba(10,14,12,0.86)";
  g.beginPath();
  g.roundRect(8, 14, 496, 68, 14);
  g.fill();
  g.fillStyle = color;
  g.fillRect(8, 14, 14, 68);
  g.fillStyle = "#fff";
  g.font = "bold 40px Arial Narrow, Arial, sans-serif";
  g.textBaseline = "middle";
  g.fillText(text.toUpperCase(), 40, 50);
  return c;
}

// ------------------------------------------------------------------ component

export default function Stadium3D({
  frame, ids, players, homeColor, awayColor, focusId, height = "100%", initialCam = "broadcast", showControls = true, celebrate = null, events, speed,
}: Stadium3DProps) {
  const mount = useRef<HTMLDivElement>(null);
  const loadingRef = useRef<HTMLDivElement>(null);
  const state = useRef<{ frame: Frame | null; ids: (string | null)[]; focusId?: string | null; cam: CamMode; players: Stadium3DProps["players"]; celebrate: Stadium3DProps["celebrate"]; events?: any[]; speed?: number }>({
    frame, ids, focusId, cam: initialCam, players, celebrate, events, speed,
  });
  const [cam, setCam] = useState<CamMode>(initialCam);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  state.current.frame = frame;
  state.current.ids = ids;
  state.current.focusId = focusId;
  state.current.players = players;
  state.current.cam = cam;
  state.current.celebrate = celebrate;
  state.current.events = events;
  state.current.speed = speed;

  useEffect(() => {
    let disposed = false;
    let raf = 0;
    let cleanup = () => {};
    (async () => {
      const THREE = await import("three");
      const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
      const SkeletonUtils = await import("three/examples/jsm/utils/SkeletonUtils.js");
      const el = mount.current;
      if (!el || disposed) return;

      // ---- renderer
      const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(el.clientWidth, el.clientHeight);
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 0.95;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      el.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#0b1622");
      scene.fog = new THREE.Fog("#0b1622", 140, 320);

      const camera = new THREE.PerspectiveCamera(34, el.clientWidth / el.clientHeight, 0.5, 600);
      camera.position.set(0, 19, 50);

      // ---- lights: night match under floodlights
      scene.add(new THREE.HemisphereLight("#cfe3ff", "#253a1f", 0.85));
      const key = new THREE.DirectionalLight("#fff6e8", 1.9);
      key.position.set(-40, 80, 50);
      key.castShadow = true;
      key.shadow.mapSize.set(2048, 2048);
      const sc = key.shadow.camera as InstanceType<typeof THREE.OrthographicCamera>;
      sc.left = -64; sc.right = 64; sc.top = 44; sc.bottom = -44; sc.near = 10; sc.far = 220;
      key.shadow.bias = -0.0004;
      key.shadow.normalBias = 0.02;
      scene.add(key);
      const fill = new THREE.DirectionalLight("#dfe9ff", 0.8);
      fill.position.set(50, 60, -50);
      scene.add(fill);

      // ---- pitch
      const grassTex = new THREE.CanvasTexture(grassCanvas());
      grassTex.colorSpace = THREE.SRGBColorSpace;
      grassTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
      const pitch = new THREE.Mesh(
        new THREE.PlaneGeometry(PITCH_L + 12, PITCH_W + 12),
        new THREE.MeshStandardMaterial({ map: grassTex, roughness: 0.92, metalness: 0 }),
      );
      pitch.rotation.x = -Math.PI / 2;
      pitch.receiveShadow = true;
      scene.add(pitch);
      const surround = new THREE.Mesh(new THREE.PlaneGeometry(220, 170), new THREE.MeshStandardMaterial({ color: "#20402a", roughness: 1 }));
      surround.rotation.x = -Math.PI / 2;
      surround.position.y = -0.02;
      surround.receiveShadow = true;
      scene.add(surround);

      // ---- goals with nets
      const postMat = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.3 });
      const netMat = new THREE.MeshBasicMaterial({ color: "#ffffff", wireframe: true, transparent: true, opacity: 0.35 });
      for (const side of [-1, 1]) {
        const g = new THREE.Group();
        const r = 0.06;
        const post = new THREE.CylinderGeometry(r, r, 2.44, 12);
        for (const z of [-3.66, 3.66]) {
          const p = new THREE.Mesh(post, postMat);
          p.position.set(0, 1.22, z);
          p.castShadow = true;
          g.add(p);
        }
        const bar = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 7.32 + 2 * r, 12), postMat);
        bar.rotation.x = Math.PI / 2;
        bar.position.set(0, 2.44, 0);
        bar.castShadow = true;
        g.add(bar);
        const net = new THREE.Mesh(new THREE.BoxGeometry(2, 2.44, 7.32, 6, 8, 20), netMat);
        net.position.set(side * 1, 1.22, 0);
        g.add(net);
        g.position.set(side * PITCH_L / 2, 0, 0);
        scene.add(g);
      }

      // ---- corner flags
      for (const [x, z] of [[-52.5, -34], [52.5, -34], [52.5, 34], [-52.5, 34]]) {
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1.5, 6), postMat);
        pole.position.set(x, 0.75, z);
        scene.add(pole);
        const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.3), new THREE.MeshStandardMaterial({ color: "#f2a900", side: THREE.DoubleSide }));
        flag.position.set(x + 0.2, 1.35, z);
        scene.add(flag);
      }

      // ---- dugouts (far side, either side of halfway) and technical areas
      for (const side of [-1, 1]) {
        const dug = new THREE.Group();
        const shell = new THREE.MeshStandardMaterial({ color: "#20262e", roughness: 0.6 });
        const back = new THREE.Mesh(new THREE.BoxGeometry(11, 2.4, 0.2), shell);
        back.position.set(0, 1.2, -1.3);
        dug.add(back);
        const roof = new THREE.Mesh(new THREE.BoxGeometry(11, 0.12, 2.8),
          new THREE.MeshStandardMaterial({ color: "#9fb7c8", transparent: true, opacity: 0.35, roughness: 0.1 }));
        roof.position.set(0, 2.4, 0);
        dug.add(roof);
        for (const x of [-5.5, 5.5]) {
          const wall = new THREE.Mesh(new THREE.BoxGeometry(0.15, 2.4, 2.8), shell);
          wall.position.set(x, 1.2, 0);
          dug.add(wall);
        }
        const seats = new THREE.Mesh(new THREE.BoxGeometry(10.6, 0.5, 0.6), new THREE.MeshStandardMaterial({ color: side < 0 ? homeColor : awayColor }));
        seats.position.set(0, 0.45, -0.8);
        dug.add(seats);
        dug.position.set(side * 9, 0, -38.6);
        scene.add(dug);
        const area = new THREE.Mesh(new THREE.PlaneGeometry(10, 3), new THREE.MeshBasicMaterial({ color: "#ffffff", wireframe: true, transparent: true, opacity: 0.45 }));
        area.rotation.x = -Math.PI / 2;
        area.position.set(side * 9, 0.02, -36);
        scene.add(area);
      }

      // ---- LED boards
      const boardTex = new THREE.CanvasTexture(boardCanvas());
      boardTex.colorSpace = THREE.SRGBColorSpace;
      boardTex.wrapS = THREE.RepeatWrapping;
      const boardMat = new THREE.MeshStandardMaterial({ map: boardTex, emissive: "#ffffff", emissiveMap: boardTex, emissiveIntensity: 0.55 });
      const boards: { w: number; pos: [number, number, number]; rotY: number }[] = [
        { w: 42, pos: [-35, 0.45, -38.5], rotY: 0 },
        { w: 42, pos: [35, 0.45, -38.5], rotY: 0 },
        { w: 110, pos: [0, 0.45, 38.5], rotY: Math.PI },
        { w: 72, pos: [-57.5, 0.45, 0], rotY: Math.PI / 2 },
        { w: 72, pos: [57.5, 0.45, 0], rotY: -Math.PI / 2 },
      ];
      const boardTextures: any[] = [];
      for (const b of boards) {
        const t = boardTex.clone();
        boardTextures.push(t);
        t.repeat.set(b.w / 110, 1);
        t.needsUpdate = true;
        const m = new THREE.Mesh(new THREE.BoxGeometry(b.w, 0.9, 0.15), boardMat.clone());
        (m.material as any).map = t;
        (m.material as any).emissiveMap = t;
        m.position.set(...b.pos);
        m.rotation.y = b.rotY;
        scene.add(m);
      }

      // ---- stands with crowd
      const crowdTex = new THREE.CanvasTexture(crowdCanvas());
      crowdTex.colorSpace = THREE.SRGBColorSpace;
      crowdTex.wrapS = crowdTex.wrapT = THREE.RepeatWrapping;
      const standDefs: { w: number; d: number; pos: [number, number]; rotY: number }[] = [
        { w: 130, d: 30, pos: [0, -42], rotY: 0 },
        { w: 84, d: 26, pos: [-62, 0], rotY: Math.PI / 2 },
        { w: 84, d: 26, pos: [62, 0], rotY: -Math.PI / 2 },
      ];
      const crowdSlopes: { mesh: any; y: number; phase: number }[] = [];
      for (const s of standDefs) {
        const g = new THREE.Group();
        const tex = crowdTex.clone();
        tex.repeat.set(s.w / 24, 3);
        tex.needsUpdate = true;
        const slope = new THREE.Mesh(new THREE.PlaneGeometry(s.w, Math.hypot(s.d, 18)),
          new THREE.MeshStandardMaterial({ map: tex, roughness: 1 }));
        slope.rotation.x = -Math.atan2(18, s.d);
        slope.position.set(0, 9 + 1.5, -s.d / 2 - 2);
        g.add(slope);
        crowdSlopes.push({ mesh: slope, y: slope.position.y, phase: Math.random() * 6 });
        const back = new THREE.Mesh(new THREE.BoxGeometry(s.w, 26, 1), new THREE.MeshStandardMaterial({ color: "#1a2029" }));
        back.position.set(0, 13, -s.d - 2.5);
        g.add(back);
        const roof = new THREE.Mesh(new THREE.BoxGeometry(s.w, 0.6, s.d * 0.75), new THREE.MeshStandardMaterial({ color: "#2a313b" }));
        roof.position.set(0, 26, -s.d * 0.62 - 2);
        g.add(roof);
        g.position.set(s.pos[0], 0, s.pos[1]);
        g.rotation.y = s.rotY;
        scene.add(g);
      }

      // ---- floodlight towers
      for (const [x, z] of [[-70, -52], [70, -52], [70, 52], [-70, 52]]) {
        const tower = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.9, 44, 8), new THREE.MeshStandardMaterial({ color: "#3a414c" }));
        tower.position.set(x, 22, z);
        scene.add(tower);
        const lamp = new THREE.Mesh(new THREE.BoxGeometry(8, 4, 1), new THREE.MeshStandardMaterial({ color: "#ffffff", emissive: "#fffbe8", emissiveIntensity: 2.5 }));
        lamp.position.set(x * 0.98, 45, z * 0.98);
        lamp.lookAt(0, 0, 0);
        scene.add(lamp);
      }

      // ---- ball
      const ballTex = new THREE.CanvasTexture(ballCanvas());
      ballTex.colorSpace = THREE.SRGBColorSpace;
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 16), new THREE.MeshStandardMaterial({ map: ballTex, roughness: 0.45 }));
      ball.castShadow = true;
      scene.add(ball);

      // ---- players
      const loader = new GLTFLoader();
      const gltf = await loader.loadAsync("/models/Soldier.glb");
      if (disposed) return;
      const base = gltf.scene;
      const box = new THREE.Box3().setFromObject(base);
      const modelH = box.max.y - box.min.y || 1.8;
      const scale = 1.8 / modelH;

      // Kit by body height (model space is z-up, centimetres): boots, socks, shorts, shirt, skin.
      const SKIN = ["#8d5524", "#c68642", "#e0ac69", "#f1c27d", "#ffdbac", "#5a3825", "#a1665e"];
      const kitMaterial = (mat: any, kitc: { shirt: string; shorts: string; socks: string; skin: string }, key: string) => {
        const m = mat.clone();
        const visor = m.name === "Vanguard_VisorMat";
        const u = {
          shirt: { value: new THREE.Color(kitc.shirt) },
          shorts: { value: new THREE.Color(kitc.shorts) },
          socks: { value: new THREE.Color(kitc.socks) },
          skin: { value: new THREE.Color(kitc.skin) },
        };
        m.onBeforeCompile = (shader: any) => {
          Object.assign(shader.uniforms, u);
          shader.vertexShader = "varying float vH;\n" + shader.vertexShader.replace(
            "#include <begin_vertex>", "#include <begin_vertex>\n vH = position.z;");
          shader.fragmentShader = "uniform vec3 shirt; uniform vec3 shorts; uniform vec3 socks; uniform vec3 skin; varying float vH;\n" +
            shader.fragmentShader.replace("#include <map_fragment>", `#include <map_fragment>
              float lum = dot(diffuseColor.rgb, vec3(0.299, 0.587, 0.114));
              vec3 kc; float amt = 0.86;
              ${visor ? "kc = skin; amt = 0.92;" : `
              if (vH < 11.0) { kc = vec3(0.06); }
              else if (vH < 46.0) { kc = socks; }
              else if (vH < 84.0) { kc = shorts; }
              else if (vH < 151.0) { kc = shirt; }
              else { kc = skin; amt = 0.9; }`}
              diffuseColor.rgb = mix(diffuseColor.rgb, kc * (0.3 + lum * 1.5), amt);`);
        };
        m.customProgramCacheKey = () => "kit-" + key + (visor ? "-v" : "");
        return m;
      };

      type P = {
        root: InstanceType<typeof THREE.Object3D>;
        mixer: InstanceType<typeof THREE.AnimationMixer>;
        idle: any; walk: any; run: any;
        pos: InstanceType<typeof THREE.Vector3>; target: InstanceType<typeof THREE.Vector3>; prevTarget: InstanceType<typeof THREE.Vector3>;
        speed: number; heading: number; visible: boolean;
        upLeg: any; knee: any; kickT: number; kickAmp: number;
      };
      const bone = (root: any, n: string) => root.getObjectByName(`mixamorig${n}`) ?? root.getObjectByName(`mixamorig:${n}`) ?? null;
      const clip = (n: string) => gltf.animations.find((a: any) => a.name === n)!;
      const people: P[] = [];
      for (let s = 0; s < 22; s++) {
        const home = s < 11;
        const gk = s === 0 || s === 11;
        const kitc = gk
          ? { shirt: home ? "#d8e021" : "#f07b2a", shorts: "#15181c", socks: home ? "#d8e021" : "#f07b2a", skin: SKIN[s % SKIN.length] }
          : { shirt: home ? homeColor : awayColor, shorts: home ? "#f4f4f2" : "#15181c", socks: home ? homeColor : awayColor, skin: SKIN[(s * 3) % SKIN.length] };
        const root = SkeletonUtils.clone(base);
        root.scale.setScalar(scale);
        root.traverse((o: any) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = false;
            o.frustumCulled = false;
            o.material = Array.isArray(o.material) ? o.material.map((mm: any) => kitMaterial(mm, kitc, String(s))) : kitMaterial(o.material, kitc, String(s));
          }
        });
        const mixer = new THREE.AnimationMixer(root);
        const idle = mixer.clipAction(clip("Idle"));
        const walk = mixer.clipAction(clip("Walk"));
        const run = mixer.clipAction(clip("Run"));
        for (const a of [idle, walk, run]) {
          a.play();
          a.setEffectiveWeight(0);
          a.time = Math.random() * a.getClip().duration;
        }
        idle.setEffectiveWeight(1);
        root.visible = false;
        scene.add(root);
        people.push({
          root, mixer, idle, walk, run,
          pos: new THREE.Vector3(), target: new THREE.Vector3(), prevTarget: new THREE.Vector3(),
          speed: 0, heading: home ? Math.PI / 2 : -Math.PI / 2, visible: false,
          upLeg: bone(root, "RightUpLeg"), knee: bone(root, "RightLeg"), kickT: -1, kickAmp: 1,
        });
      }

      // ---- officials, managers, substitutes, warm-ups
      type Extra = P & { role: string; vmax: number; anchor: InstanceType<typeof THREE.Vector3>; phase: number };
      const extras: Extra[] = [];
      const spawn = (role: string, kitc: { shirt: string; shorts: string; socks: string; skin: string }, at: [number, number], vmax: number) => {
        const root = SkeletonUtils.clone(base);
        root.scale.setScalar(scale);
        const key = role + extras.length;
        root.traverse((o: any) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.frustumCulled = false;
            o.material = Array.isArray(o.material) ? o.material.map((mm: any) => kitMaterial(mm, kitc, key)) : kitMaterial(o.material, kitc, key);
          }
        });
        const mixer = new THREE.AnimationMixer(root);
        const idle = mixer.clipAction(clip("Idle")), walk = mixer.clipAction(clip("Walk")), run = mixer.clipAction(clip("Run"));
        for (const a of [idle, walk, run]) { a.play(); a.setEffectiveWeight(0); a.time = Math.random() * a.getClip().duration; }
        idle.setEffectiveWeight(1);
        const pos = new THREE.Vector3(at[0], 0, at[1]);
        root.position.copy(pos);
        scene.add(root);
        extras.push({ role, vmax, root, mixer, idle, walk, run, pos, target: pos.clone(), prevTarget: pos.clone(), speed: 0,
          heading: 0, visible: true, anchor: pos.clone(), phase: Math.random() * 10, upLeg: null, knee: null, kickT: -1, kickAmp: 0 });
      };
      const refKit = { shirt: "#151515", shorts: "#151515", socks: "#151515", skin: SKIN[1] };
      const asstKit = { shirt: "#e9d41b", shorts: "#151515", socks: "#151515", skin: SKIN[3] };
      spawn("referee", refKit, [0, 6], 7.2);
      spawn("ar-far", asstKit, [20, -35.2], 7.0);
      spawn("ar-near", { ...asstKit, skin: SKIN[4] }, [-20, 35.2], 7.0);
      spawn("fourth", { ...refKit, skin: SKIN[5] }, [0, -36.2], 2);
      for (const side of [-1, 1]) {
        const homeSide = side < 0;
        const team = homeSide ? homeColor : awayColor;
        spawn("coach", { shirt: "#1b2230", shorts: "#1b2230", socks: "#101114", skin: SKIN[homeSide ? 2 : 0] }, [side * 9, -35.6], 2.4);
        spawn("bench", { shirt: team, shorts: "#1b2230", socks: "#101114", skin: SKIN[homeSide ? 6 : 4] }, [side * 9 + side * 4.4, -38.9], 0.5);
        for (let i = 0; i < 4; i++) {
          spawn("bench", { shirt: team, shorts: team, socks: "#101114", skin: SKIN[(i * 2 + (homeSide ? 1 : 3)) % SKIN.length] },
            [side * 9 - 3.6 + i * 2.2, -38.9], 0.5);
        }
        const bib = homeSide ? "#ff7a00" : "#22c55e";
        for (let i = 0; i < 3; i++) {
          spawn("warmup", { shirt: bib, shorts: homeSide ? "#f4f4f2" : "#15181c", socks: team, skin: SKIN[(i * 3 + (homeSide ? 2 : 5)) % SKIN.length] },
            [side * 59, -24 + i * 3], 3.2);
        }
      }
      const steer = (e: Extra, dt: number, look: InstanceType<typeof THREE.Vector3>) => {
        tmp.subVectors(e.target, e.pos);
        const d = tmp.length();
        const v = Math.min(e.vmax, d / 0.7);
        if (d > 0.02) e.pos.addScaledVector(tmp.normalize(), Math.min(d, v * dt));
        e.speed = e.speed * 0.85 + (d > 0.05 ? v : 0) * 0.15;
        e.root.position.copy(e.pos);
        let want = e.heading;
        if (d > 0.3) want = Math.atan2(tmp.x, tmp.z);
        else { tmp.subVectors(look, e.pos); want = Math.atan2(tmp.x, tmp.z); }
        let dh = want - e.heading;
        while (dh > Math.PI) dh -= Math.PI * 2;
        while (dh < -Math.PI) dh += Math.PI * 2;
        e.heading += dh * Math.min(1, dt * 5);
        e.root.rotation.y = e.heading + Math.PI;
        const wRun = Math.min(1, Math.max(0, (e.speed - 2.6) / 1.6));
        const wWalk = Math.min(1, Math.max(0, e.speed / 1.2)) * (1 - wRun);
        e.idle.setEffectiveWeight(Math.max(0, 1 - wRun - wWalk));
        e.walk.setEffectiveWeight(wWalk);
        e.run.setEffectiveWeight(wRun);
        e.walk.timeScale = Math.max(0.6, e.speed / 1.5);
        e.run.timeScale = Math.max(0.7, e.speed / 5.2);
        e.mixer.update(dt);
      };

      // ---- focus label
      let labelSprite: any = null;
      let labelFor = "";
      const setLabel = (pid: string | null) => {
        if (pid === labelFor) return;
        labelFor = pid ?? "";
        if (labelSprite) { scene.remove(labelSprite); labelSprite.material.map.dispose(); labelSprite = null; }
        if (!pid) return;
        const p = state.current.players[pid];
        if (!p) return;
        const slot = state.current.ids.indexOf(pid);
        const tex = new THREE.CanvasTexture(labelCanvas(`${p.number}  ${p.short_name ?? p.short ?? p.name}`, slot < 11 ? homeColor : awayColor));
        tex.colorSpace = THREE.SRGBColorSpace;
        labelSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
        labelSprite.scale.set(5.4, 1.0, 1);
        labelSprite.renderOrder = 10;
        scene.add(labelSprite);
      };

      // ---- frame ingestion
      let lastFrameRef: Frame | null = null;
      let lastFrameTime = performance.now();
      let frameDt = 0.125;
      const ballTarget = new THREE.Vector3(0, 0.11, 0);
      const ballPos = new THREE.Vector3(0, 0.11, 0);
      const ballPrev = new THREE.Vector3(0, 0.11, 0);
      let ballSpeed = 0;
      const ingest = (f: Frame) => {
        const now = performance.now();
        frameDt = Math.min(Math.max((now - lastFrameTime) / 1000, 0.05), 0.5);
        lastFrameTime = now;
        f.p.forEach((pt, s) => {
          const pp = people[s];
          if (!pt) { pp.visible = false; pp.root.visible = false; return; }
          const x = pt[0] - PITCH_L / 2, z = pt[1] - PITCH_W / 2;
          pp.prevTarget.copy(pp.target);
          pp.target.set(x, 0, z);
          if (!pp.visible) { pp.pos.copy(pp.target); pp.prevTarget.copy(pp.target); }
          pp.visible = true;
          pp.root.visible = true;
          const sp = pp.prevTarget.distanceTo(pp.target) / frameDt;
          pp.speed = pp.speed * 0.6 + Math.min(sp, 10) * 0.4;
        });
        ballPrev.copy(ballTarget);
        ballTarget.set(f.b[0] - PITCH_L / 2, 0.11, f.b[1] - PITCH_W / 2);
        ballSpeed = ballPrev.distanceTo(ballTarget) / frameDt;
      };

      // ---- camera rig
      const camPos = new THREE.Vector3(0, 19, 50);
      const camLook = new THREE.Vector3();

      const clock = new THREE.Clock();
      let crowdExcite = 0;
      let lastCelebrate = 0;
      const tmp = new THREE.Vector3();
      const tmpAxis = new THREE.Vector3();
      const prevBall = new THREE.Vector3();
      const spinAxis = new THREE.Vector3();
      const spinQ = new THREE.Quaternion();
      const pq = new THREE.Quaternion();
      const dq = new THREE.Quaternion();
      /** Rotate a bone about a world-space axis (applied after the animation mixer). */
      const rotateBoneWorld = (b: any, axis: InstanceType<typeof THREE.Vector3>, angle: number) => {
        b.parent.getWorldQuaternion(pq);
        dq.setFromAxisAngle(axis, angle);
        const local = pq.clone().invert().multiply(dq).multiply(pq);
        b.quaternion.premultiply(local);
      };

      type Flight = {
        from: InstanceType<typeof THREE.Vector3>; to: InstanceType<typeof THREE.Vector3>; t: number; dur: number;
        arc: number; h0: number; ground: boolean; after: string | null; goal: boolean; bounce: number;
      };
      let flight: Flight | null = null;
      let carrier: string | null = null;
      let holding = false;
      let deadAt: InstanceType<typeof THREE.Vector3> | null = null;
      let lastSeq = 0;
      let touchPhase = 0;
      const W = (x: number, y: number) => new THREE.Vector3(x - PITCH_L / 2, 0.11, y - PITCH_W / 2);
      const kickBy = (pid: string | null, amp: number, at: InstanceType<typeof THREE.Vector3>, toward: InstanceType<typeof THREE.Vector3>) => {
        const s = pid ? state.current.ids.indexOf(pid) : -1;
        if (s < 0) return;
        const p = people[s];
        const dx = toward.x - at.x, dz = toward.z - at.z;
        p.heading = Math.atan2(dx, dz);
        const n = Math.hypot(dx, dz) || 1;
        // Step the kicker onto the ball so foot meets ball.
        p.pos.lerp(tmp.set(at.x - (dx / n) * 0.55, 0, at.z - (dz / n) * 0.55), 0.85);
        p.kickT = 0;
        p.kickAmp = amp;
      };
      const onEvent = (e: any, speed: number) => {
        const real = (d: number) => Math.max(0.18, Math.min(d / Math.max(speed, 0.25), 3.2));
        switch (e.type) {
          case "pass":
          case "clearance":
          case "shot": {
            const start = W(e.x, e.y);
            const end = W(e.end_x ?? e.x, e.end_y ?? e.y);
            const dist = start.distanceTo(end);
            let arc = 0, ground = true, h0 = 0, bounce = 0;
            if (e.type === "clearance") { arc = 9 + dist * 0.12; ground = false; bounce = 1; }
            else if (e.type === "shot") {
              ground = false;
              h0 = e.body_part === "head" ? 1.75 : 0;
              arc = e.body_part === "head" ? 0.15 : 0.3 + Math.random() * 1.3;
              if (e.outcome === "goal") { end.x += Math.sign(end.x) * 1.4; end.y = 0.11; }
            } else if (e.pass_type === "long" || e.pass_type === "switch") { ground = false; arc = Math.min(13, 3 + dist * 0.17); bounce = 0.8; }
            else if (e.pass_type === "cross") { ground = false; arc = 3.5 + Math.random() * 2.5; }
            else if (e.pass_type === "through" && dist > 22) { ground = false; arc = 0.9; }
            kickBy(e.player_id, e.type === "shot" ? 1.25 : e.type === "clearance" ? 1.3 : ground ? 0.7 : 1.05, start, end);
            flight = {
              from: start, to: end, t: 0, dur: real(e.duration || dist / 18), arc, h0, ground,
              after: e.type === "pass" && e.outcome === "complete" ? e.recipient_id : null,
              goal: e.type === "shot" && e.outcome === "goal", bounce,
            };
            carrier = null; holding = false; deadAt = null;
            break;
          }
          case "carry":
          case "dribble":
          case "interception":
          case "tackle":
            if (flight && flight.t < flight.dur * 0.85 && e.type === "carry") break; // let the pass arrive first
            flight = null; carrier = e.player_id; holding = false;
            if (e.type !== "carry") deadAt = null;
            break;
          case "save":
            flight = null; carrier = e.player_id; holding = e.outcome === "held"; deadAt = null;
            break;
          case "kickoff":
          case "free_kick":
          case "throw_in":
          case "corner":
          case "goal_kick":
            flight = null; deadAt = W(e.x, e.y); carrier = e.player_id; holding = e.type === "throw_in";
            if (e.type === "kickoff") deadAt = W(52.5, 34);
            break;
          case "ball_out":
            carrier = null;
            break;
        }
      };
      setReady(true);

      const loop = () => {
        raf = requestAnimationFrame(loop);
        if (loadingRef.current) loadingRef.current.style.display = "none";
        const dt = Math.min(clock.getDelta(), 0.1);
        const st = state.current;
        if (st.frame && st.frame !== lastFrameRef) {
          lastFrameRef = st.frame;
          ingest(st.frame);
        }
        // Players: smooth toward targets, face direction of travel, blend gait by speed.
        const k = 1 - Math.exp(-dt / (frameDt * 0.9));
        for (const p of people) {
          if (!p.visible) continue;
          p.pos.lerp(p.target, k);
          p.root.position.copy(p.pos);
          tmp.subVectors(p.target, p.prevTarget);
          let want = p.heading;
          if (tmp.lengthSq() > 0.0004) want = Math.atan2(tmp.x, tmp.z);
          else { tmp.subVectors(ballPos, p.pos); if (tmp.lengthSq() > 0.01) want = Math.atan2(tmp.x, tmp.z); }
          let d = want - p.heading;
          while (d > Math.PI) d -= Math.PI * 2;
          while (d < -Math.PI) d += Math.PI * 2;
          p.heading += d * Math.min(1, dt * 7);
          p.root.rotation.y = p.heading + Math.PI; // model's front faces -Z
          const v = p.speed;
          const wRun = Math.min(1, Math.max(0, (v - 2.6) / 1.6));
          const wWalk = Math.min(1, Math.max(0, v / 1.4)) * (1 - wRun);
          const wIdle = Math.max(0, 1 - wRun - wWalk);
          p.idle.setEffectiveWeight(wIdle);
          p.walk.setEffectiveWeight(wWalk);
          p.run.setEffectiveWeight(wRun);
          p.walk.timeScale = Math.max(0.6, v / 1.5);
          p.run.timeScale = Math.max(0.7, v / 5.2);
          p.mixer.update(dt);
          // Kicking: procedural right-leg swing layered on top of the run/walk cycle.
          if (p.kickT >= 0 && p.upLeg) {
            p.kickT += dt;
            const u = p.kickT / 0.42;
            if (u >= 1) p.kickT = -1;
            else {
              const back = -0.75, fwd = 1.35;
              const hip = u < 0.35 ? back * (u / 0.35) : u < 0.6 ? back + (fwd - back) * ((u - 0.35) / 0.25) : fwd * (1 - (u - 0.6) / 0.4);
              const kneeBend = u < 0.35 ? -1.25 * (u / 0.35) : u < 0.6 ? -1.25 * (1 - (u - 0.35) / 0.25) : 0;
              const axis = tmpAxis.set(-Math.cos(p.heading), 0, Math.sin(p.heading)); // facing × up
              p.root.updateMatrixWorld(true);
              rotateBoneWorld(p.upLeg, axis, hip * p.kickAmp);
              if (p.knee) rotateBoneWorld(p.knee, axis, kneeBend * p.kickAmp);
            }
          }
        }

        // Ball: driven by the event feed — kicked, rolled, lofted, dribbled, held.
        if (st.events && st.events.length) {
          const evs = st.events;
          const maxSeq = evs[evs.length - 1].seq;
          if (lastSeq === 0) lastSeq = maxSeq; // don't replay history on load
          else if (maxSeq > lastSeq) {
            const fresh = evs.filter((e: any) => e.seq > lastSeq).slice(-4);
            lastSeq = maxSeq;
            for (const e of fresh) onEvent(e, st.speed ?? 8);
          }
        }
        prevBall.copy(ballPos);
        if (flight) {
          flight.t += dt;
          const u = Math.min(1, flight.t / flight.dur);
          const ue = flight.ground ? 1 - Math.pow(1 - u, 1.8) : u;
          ballPos.x = flight.from.x + (flight.to.x - flight.from.x) * ue;
          ballPos.z = flight.from.z + (flight.to.z - flight.from.z) * ue;
          ballPos.y = 0.11 + flight.arc * 4 * ue * (1 - ue) + flight.h0 * (1 - ue);
          if (u >= 1) {
            if (flight.goal) { deadAt = flight.to.clone(); deadAt.y = 0.11; carrier = null; }
            else if (flight.after) { carrier = flight.after; holding = false; }
            else if (flight.bounce > 0.3) {
              // Long balls bounce once before settling.
              const dir = tmp.subVectors(flight.to, flight.from).normalize();
              flight = { from: flight.to.clone(), to: flight.to.clone().addScaledVector(dir, flight.bounce * 3), t: 0, dur: 0.45,
                arc: flight.bounce * 0.5, h0: 0, ground: false, after: null, goal: false, bounce: 0 };
            }
            if (flight && flight.t >= flight.dur) flight = null;
          }
        } else {
          const cs = carrier ? st.ids.indexOf(carrier) : -1;
          const cp = cs >= 0 ? people[cs] : null;
          if (cp && cp.visible && !(deadAt && cp.pos.distanceTo(deadAt) > 2.2)) {
            const fx = Math.sin(cp.heading), fz = Math.cos(cp.heading);
            if (holding) {
              ballPos.lerp(tmp.set(cp.pos.x + fx * 0.35, 1.05, cp.pos.z + fz * 0.35), Math.min(1, dt * 10));
            } else {
              const v = cp.speed;
              let d = 0.38;
              if (v > 1.2) {
                const before = Math.floor(touchPhase);
                touchPhase += dt * (0.7 + v * 0.22);
                if (Math.floor(touchPhase) !== before) { cp.kickT = 0; cp.kickAmp = 0.28; } // a touch
                d = 0.38 + 1.15 * Math.pow(1 - (touchPhase % 1), 2);
              }
              ballPos.x += (cp.pos.x + fx * d - ballPos.x) * Math.min(1, dt * 14);
              ballPos.z += (cp.pos.z + fz * d - ballPos.z) * Math.min(1, dt * 14);
              ballPos.y += (0.11 - ballPos.y) * Math.min(1, dt * 10);
              if (deadAt && cp.pos.distanceTo(deadAt) < 2.2) deadAt = null;
            }
          } else if (deadAt) {
            ballPos.lerp(deadAt, Math.min(1, dt * 6));
          } else {
            // No event context: follow the tracking ball.
            ballPos.x += (ballTarget.x - ballPos.x) * k;
            ballPos.z += (ballTarget.z - ballPos.z) * k;
            const loft = Math.min(3.2, Math.max(0, (ballSpeed - 14) * 0.18));
            ballPos.y += (0.11 + loft - ballPos.y) * Math.min(1, dt * 4);
          }
        }
        ball.position.copy(ballPos);
        // Rolling spin: rotate about the axis perpendicular to travel.
        tmp.subVectors(ballPos, prevBall);
        const travelled = Math.hypot(tmp.x, tmp.z);
        if (travelled > 1e-4) {
          spinAxis.set(tmp.z, 0, -tmp.x).normalize();
          spinQ.setFromAxisAngle(spinAxis, travelled / 0.11);
          ball.quaternion.premultiply(spinQ);
        }

        // Officials and bench follow the game.
        const tNow = clock.elapsedTime;
        for (const e of extras) {
          if (e.role === "referee") e.target.set(THREE.MathUtils.clamp(ballPos.x * 0.85 - 5, -45, 45), 0, THREE.MathUtils.clamp(ballPos.z * 0.6 + 7, -28, 28));
          else if (e.role === "ar-far") e.target.set(THREE.MathUtils.clamp(ballPos.x, 2, 50), 0, -35.2);
          else if (e.role === "ar-near") e.target.set(THREE.MathUtils.clamp(ballPos.x, -50, -2), 0, 35.2);
          else if (e.role === "coach") e.target.set(e.anchor.x + Math.sin(tNow * 0.35 + e.phase) * 3.2, 0, e.anchor.z + Math.sin(tNow * 0.21 + e.phase) * 0.6);
          else if (e.role === "warmup") e.target.set(e.anchor.x + Math.sin(tNow * 0.18 + e.phase) * 1.5, 0, e.anchor.z + Math.sin(tNow * 0.32 + e.phase) * 9);
          steer(e, dt, ballPos);
        }
        // Crowd bounces on big moments; LED boards scroll.
        if (st.celebrate && st.celebrate.at !== lastCelebrate) { lastCelebrate = st.celebrate.at; crowdExcite = 1; }
        crowdExcite *= Math.exp(-dt / 6);
        for (const c of crowdSlopes) c.mesh.position.y = c.y + Math.max(0, Math.sin(tNow * 11 + c.phase)) * 0.5 * crowdExcite + Math.sin(tNow * 1.3 + c.phase) * 0.03;
        for (const t of boardTextures) t.offset.x = (t.offset.x + dt * 0.012) % 1;

        // Real-time name tag: the followed player, otherwise whoever has the ball.
        const focus = st.focusId && st.ids.includes(st.focusId) ? st.focusId : null;
        const tagged = focus ?? (carrier && st.ids.includes(carrier) && !flight ? carrier : null);
        setLabel(tagged);
        if (labelSprite && tagged) {
          const p = people[st.ids.indexOf(tagged)];
          labelSprite.position.set(p.pos.x, 2.6, p.pos.z);
        }

        // Camera.
        const mode = st.cam === "follow" && !focus ? "broadcast" : st.cam;
        if (mode === "broadcast") {
          const bx = THREE.MathUtils.clamp(ballPos.x * 0.85, -36, 36);
          camPos.lerp(tmp.set(bx, 19, 50 + Math.abs(ballPos.z) * 0.1), Math.min(1, dt * 1.2));
          camLook.lerp(tmp.set(ballPos.x * 0.92, 0, ballPos.z * 0.55), Math.min(1, dt * 2));
          camera.fov += (26 - camera.fov) * Math.min(1, dt * 2);
        } else if (mode === "tactical") {
          camPos.lerp(tmp.set(ballPos.x * 0.3, 92, 34), Math.min(1, dt * 1.5));
          camLook.lerp(tmp.set(ballPos.x * 0.3, 0, 2), Math.min(1, dt * 2));
          camera.fov += (40 - camera.fov) * Math.min(1, dt * 2);
        } else if (focus) {
          const p = people[st.ids.indexOf(focus)];
          const behind = tmp.set(-Math.sin(p.heading) * 9, 4.5, -Math.cos(p.heading) * 9).add(p.pos);
          camPos.lerp(behind, Math.min(1, dt * 1.6));
          camLook.lerp(tmp.set(p.pos.x * 0.6 + ballPos.x * 0.4, 1.2, p.pos.z * 0.6 + ballPos.z * 0.4), Math.min(1, dt * 3));
          camera.fov += (45 - camera.fov) * Math.min(1, dt * 2);
        }
        camera.position.copy(camPos);
        camera.lookAt(camLook);
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
      };
      loop();

      const ro = new ResizeObserver(() => {
        if (!el) return;
        renderer.setSize(el.clientWidth, el.clientHeight);
        camera.aspect = el.clientWidth / Math.max(el.clientHeight, 1);
        camera.updateProjectionMatrix();
      });
      ro.observe(el);

      cleanup = () => {
        ro.disconnect();
        cancelAnimationFrame(raf);
        renderer.dispose();
        scene.traverse((o: any) => {
          o.geometry?.dispose?.();
          const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
          mats.forEach((m: any) => { m.map?.dispose?.(); m.dispose?.(); });
        });
        renderer.domElement.remove();
      };
    })().catch((e) => setError(String(e?.message ?? e)));
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      cleanup();
    };
    // Kits are fixed per match; rebuild only if colours change.
  }, [homeColor, awayColor]);

  return (
    <div style={{ position: "relative", width: "100%", height, minHeight: 280, borderRadius: 12, overflow: "hidden", background: "#0b1622" }}>
      <div ref={mount} style={{ position: "absolute", inset: 0 }} />
      {!ready && !error && (
        <div ref={loadingRef} style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "#9fb3aa", fontSize: 14 }}>
          <span className="analysing" style={{ color: "#9fb3aa" }}><i /><i /><i /> Loading stadium and players…</span>
        </div>
      )}
      {error && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "#f08a84", padding: 20, textAlign: "center" }}>3D view unavailable: {error}</div>}
      {showControls && ready && (
        <div className="seg" style={{ position: "absolute", right: 12, bottom: 12, background: "rgba(15,20,18,0.72)", borderColor: "rgba(255,255,255,0.12)" }}>
          {([["broadcast", "TV camera"], ["tactical", "Tactical"], ["follow", "Player cam"]] as [CamMode, string][]).map(([m, label]) => (
            <button key={m} className={cam === m ? "on" : ""} style={cam === m ? undefined : { color: "#cfd8d3" }} onClick={() => setCam(m)} disabled={m === "follow" && !focusId} title={m === "follow" && !focusId ? "Choose Player cam mode and a player first" : undefined}>
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
