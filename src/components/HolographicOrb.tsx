/* =============================================
   HolographicOrb — Three.js / React Three Fiber
   3D holographic globe with:
     • lat/lon wireframe sphere (EdgesGeometry for crisp lines)
     • 3 concentric segmented torus rings (properly distributed arcs)
     • multi-layered glowing core (white-hot center + cyan bloom)
     • orbiting particles (Points) with 3D orbital tilt
     • restrained scanning ring sweep
     • per-state color + animation mapping
     • WebGL failure fallback
   ============================================= */
import { Suspense, useRef, useMemo, useState, useEffect, useCallback } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { AdaptiveDpr } from '@react-three/drei';
import * as THREE from 'three';
import type { AssistantState, StateConfig } from '../types/jarvis';
import { STATE_CONFIGS } from '../types/jarvis';
import './HolographicOrb.css';

/* ─── helpers ─── */
const tmpColor = new THREE.Color();
const lerpColor = (cur: THREE.Color, target: THREE.Color, t: number) =>
  cur.lerp(target, t);

/* ═══════════════════════════════════
   Sub-components (inside Canvas)
   ═══════════════════════════════════ */

/* ── Wireframe Globe ── */
function WireframeGlobe({ cfg, state }: { cfg: StateConfig; state: AssistantState }) {
  const groupRef = useRef<THREE.Group>(null!);

  /* latitude rings — use lineLoop for crisp thin circles */
  const latitudes = useMemo(() => {
    const lats: { y: number; r: number }[] = [];
    for (const lat of [-60, -35, -15, 0, 15, 35, 60]) {
      const phi = THREE.MathUtils.degToRad(90 - lat);
      lats.push({ y: Math.cos(phi), r: Math.sin(phi) });
    }
    return lats;
  }, []);

  /* longitude great-circle geometries */
  const lonGeometries = useMemo(() => {
    const geos: THREE.BufferGeometry[] = [];
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * Math.PI;
      const pts: THREE.Vector3[] = [];
      for (let j = 0; j <= 64; j++) {
        const theta = (j / 64) * Math.PI * 2;
        const x = Math.cos(theta) * Math.sin(angle);
        const y = Math.sin(theta);
        const z = Math.cos(theta) * Math.cos(angle);
        pts.push(new THREE.Vector3(x, y, z));
      }
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      geos.push(geo);
    }
    return geos;
  }, []);

  useFrame((_s, dt) => {
    if (!groupRef.current) return;
    groupRef.current.rotation.y += dt * cfg.ringSpeed * 0.2;
    // gentle tilt toward viewer
    groupRef.current.rotation.x = THREE.MathUtils.lerp(
      groupRef.current.rotation.x, 0.18, dt * 1.5,
    );
  });

  const baseOpacity = state === 'ERROR' ? 0.06 : state === 'MUTED' ? 0.12 : 0.22;

  return (
    <group ref={groupRef}>
      {/* Latitude circles */}
      {latitudes.map((l, i) => {
        const pts: THREE.Vector3[] = [];
        for (let j = 0; j <= 80; j++) {
          const a = (j / 80) * Math.PI * 2;
          pts.push(new THREE.Vector3(Math.cos(a) * l.r, l.y, Math.sin(a) * l.r));
        }
        const geo = new THREE.BufferGeometry().setFromPoints(pts);
        const isEquator = i === 3;
        return (
          <lineLoop key={`lat-${i}`} geometry={geo}>
            <lineBasicMaterial
              color={cfg.color}
              transparent
              opacity={isEquator ? baseOpacity * 1.4 : baseOpacity * 0.8}
              depthWrite={false}
            />
          </lineLoop>
        );
      })}

      {/* Longitude great circles */}
      {lonGeometries.map((geo, i) => (
        <lineLoop key={`lon-${i}`} geometry={geo}>
          <lineBasicMaterial
            color={cfg.color}
            transparent
            opacity={baseOpacity * 0.6}
            depthWrite={false}
          />
        </lineLoop>
      ))}
    </group>
  );
}

/* ── Concentric Torus Rings ── */
function OrbitalRings({ cfg }: { cfg: StateConfig }) {
  const rings = useMemo(() => [
    { radius: 1.12, tube: 0.012, tiltX: 0.30,  tiltZ: 0.08,  speedMul:  1.0,  opacity: 0.40, segments: 3 },
    { radius: 1.23, tube: 0.009, tiltX: -0.20, tiltZ: -0.12, speedMul: -0.65, opacity: 0.30, segments: 4 },
    { radius: 1.34, tube: 0.007, tiltX:  0.14, tiltZ:  0.22, speedMul:  0.50, opacity: 0.22, segments: 5 },
  ], []);

  return (
    <group>
      {rings.map((r, ri) => (
        <RingSegmented
          key={ri}
          radius={r.radius}
          tube={r.tube}
          tiltX={r.tiltX}
          tiltZ={r.tiltZ}
          speedMul={r.speedMul}
          opacity={r.opacity}
          segments={r.segments}
          cfg={cfg}
        />
      ))}
    </group>
  );
}

/* Each ring is broken into evenly-distributed arc segments with gaps */
function RingSegmented({
  radius, tube, tiltX, tiltZ, speedMul, opacity, segments, cfg,
}: {
  radius: number; tube: number; tiltX: number; tiltZ: number;
  speedMul: number; opacity: number; segments: number;
  cfg: StateConfig;
}) {
  const groupRef = useRef<THREE.Group>(null!);

  const gapFrac = 0.15;
  const segAngle = (Math.PI * 2) / segments;
  const arcAngle = segAngle * (1 - gapFrac);

  /* Create pre-rotated torus geometries so arcs distribute evenly.
     TorusGeometry lies in the XY plane; rotating around Z places each
     arc in its correct angular slot around the equator. */
  const segmentGeometries = useMemo(() => {
    return Array.from({ length: segments }, (_, i) => {
      const geo = new THREE.TorusGeometry(radius, tube, 8, 48, arcAngle);
      geo.rotateZ(i * segAngle);
      return geo;
    });
  }, [radius, tube, arcAngle, segAngle, segments]);

  useFrame((_s, dt) => {
    if (!groupRef.current) return;
    groupRef.current.rotation.y += dt * cfg.ringSpeed * speedMul;
  });

  return (
    <group ref={groupRef} rotation={[tiltX, 0, tiltZ]}>
      {segmentGeometries.map((geo, i) => (
        <mesh key={i} geometry={geo}>
          <meshBasicMaterial
            color={cfg.color}
            transparent
            opacity={opacity}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

/* ── Multi-Layer Glowing Core ── */
function GlowingCore({ cfg }: { cfg: StateConfig }) {
  const outerRef = useRef<THREE.Mesh>(null!);
  const midRef   = useRef<THREE.Mesh>(null!);
  const cyanRef  = useRef<THREE.Mesh>(null!);
  const innerRef = useRef<THREE.Mesh>(null!);
  const lightRef  = useRef<THREE.PointLight>(null!);
  const light2Ref = useRef<THREE.PointLight>(null!);

  useFrame((s) => {
    const t = s.clock.elapsedTime;
    const pulse   = 1 + Math.sin(t * 2.5) * 0.15 * cfg.pulseIntensity;
    const breathe = 1 + Math.sin(t * 1.2) * 0.06;

    // Outer diffuse glow
    if (outerRef.current) {
      outerRef.current.scale.setScalar(0.44 * cfg.coreScale * pulse * breathe);
      const mat = outerRef.current.material as THREE.MeshBasicMaterial;
      lerpColor(mat.color, tmpColor.set(cfg.color), 0.06);
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, 0.22 * cfg.pulseIntensity, 0.05);
    }

    // Mid glow layer
    if (midRef.current) {
      midRef.current.scale.setScalar(0.20 * cfg.coreScale * pulse);
      const mat = midRef.current.material as THREE.MeshBasicMaterial;
      lerpColor(mat.color, tmpColor.set(cfg.color), 0.06);
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, 0.55 * cfg.pulseIntensity, 0.05);
    }

    // Restrained cyan halo (always cyan, wraps inner white-hot core)
    if (cyanRef.current) {
      cyanRef.current.scale.setScalar(0.12 * cfg.coreScale * pulse);
      const mat = cyanRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, 0.50 * cfg.pulseIntensity, 0.05);
    }

    // Inner white-hot center — slightly dimmed so cyan shows through
    if (innerRef.current) {
      innerRef.current.scale.setScalar(0.08 * cfg.coreScale * pulse);
    }

    // Primary coloured point light
    if (lightRef.current) {
      lerpColor(lightRef.current.color, tmpColor.set(cfg.color), 0.06);
      lightRef.current.intensity = THREE.MathUtils.lerp(
        lightRef.current.intensity,
        3.5 * cfg.pulseIntensity * pulse,
        0.06,
      );
    }

    // Secondary white fill light (softer)
    if (light2Ref.current) {
      light2Ref.current.intensity = THREE.MathUtils.lerp(
        light2Ref.current.intensity,
        1.2 * cfg.pulseIntensity * pulse,
        0.06,
      );
    }
  });

  return (
    <>
      {/* Outer diffuse glow */}
      <mesh ref={outerRef}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial
          color={cfg.color}
          transparent
          opacity={0.18}
          depthWrite={false}
        />
      </mesh>

      {/* Mid bright glow */}
      <mesh ref={midRef}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial
          color={cfg.color}
          transparent
          opacity={0.45}
          depthWrite={false}
        />
      </mesh>

      {/* Cyan halo — restrained glow wrapping the hot core */}
      <mesh ref={cyanRef}>
        <sphereGeometry args={[1, 16, 16]} />
        <meshBasicMaterial
          color="#00d4ff"
          transparent
          opacity={0.40}
          depthWrite={false}
        />
      </mesh>

      {/* Inner white-hot center */}
      <mesh ref={innerRef}>
        <sphereGeometry args={[1, 16, 16]} />
        <meshBasicMaterial
          color="#ffffff"
          transparent
          opacity={0.85}
          depthWrite={false}
        />
      </mesh>

      {/* Coloured point light */}
      <pointLight ref={lightRef} color={cfg.color} intensity={3} distance={10} decay={2} />
      {/* White fill light */}
      <pointLight ref={light2Ref} color="#ffffff" intensity={0.9} distance={5} decay={2} />
    </>
  );
}

/* ── Orbiting Particles ── */
function OrbParticles({ cfg }: { cfg: StateConfig }) {
  const pointsRef = useRef<THREE.Points>(null!);

  const MAX = 20;
  const { positions, seeds } = useMemo(() => {
    const pos = new Float32Array(MAX * 3);
    const sd = new Float32Array(MAX * 5); // angle, radius, speed, tiltPhase, tiltAmp
    for (let i = 0; i < MAX; i++) {
      sd[i * 5 + 0] = Math.random() * Math.PI * 2;          // angle
      sd[i * 5 + 1] = 1.05 + Math.random() * 0.28;          // orbit radius (just outside globe)
      sd[i * 5 + 2] = 0.12 + Math.random() * 0.30;          // speed
      sd[i * 5 + 3] = Math.random() * Math.PI * 2;           // tilt phase
      sd[i * 5 + 4] = 0.10 + Math.random() * 0.30;          // tilt amplitude
    }
    return { positions: pos, seeds: sd };
  }, []);

  useFrame((s) => {
    if (!pointsRef.current) return;
    const t = s.clock.elapsedTime;
    const posAttr = pointsRef.current.geometry.getAttribute('position') as THREE.BufferAttribute;
    const n = Math.min(cfg.particleCount, MAX);

    for (let i = 0; i < MAX; i++) {
      if (i < n) {
        const a = seeds[i * 5 + 0] + t * seeds[i * 5 + 2] * cfg.ringSpeed;
        const r = seeds[i * 5 + 1];
        const tiltY = Math.sin(seeds[i * 5 + 3] + t * 0.4) * seeds[i * 5 + 4];
        posAttr.setXYZ(i, Math.cos(a) * r, tiltY, Math.sin(a) * r);
      } else {
        posAttr.setXYZ(i, 0, 100, 0);
      }
    }
    posAttr.needsUpdate = true;

    const mat = pointsRef.current.material as THREE.PointsMaterial;
    lerpColor(mat.color, tmpColor.set(cfg.color), 0.06);
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={MAX}
        />
      </bufferGeometry>
      <pointsMaterial
        color={cfg.color}
        size={0.04}
        transparent
        opacity={0.75}
        depthWrite={false}
        sizeAttenuation
      />
    </points>
  );
}

/* ── Scanning Ring (replaces oversized plane) ── */
function ScanRing({ cfg, state }: { cfg: StateConfig; state: AssistantState }) {
  const meshRef = useRef<THREE.Mesh>(null!);
  const matRef = useRef<THREE.MeshBasicMaterial>(null!);

  const active = state === 'LISTENING' || state === 'THINKING' || state === 'CONNECTING';

  useFrame((s, dt) => {
    if (!meshRef.current || !matRef.current) return;
    const t = s.clock.elapsedTime;

    // Sweep up/down through the sphere
    const sweepY = Math.sin(t * 1.4) * 0.95;
    meshRef.current.position.y = sweepY;
    meshRef.current.rotation.x = Math.PI / 2;

    // Ring radius shrinks as it moves away from equator (matches sphere cross-section)
    const normalizedY = Math.abs(sweepY);
    const ringR = Math.sqrt(Math.max(0, 1 - normalizedY * normalizedY));
    meshRef.current.scale.setScalar(ringR > 0.05 ? ringR : 0.05);

    const targetOpacity = active ? 0.2 : 0.0;
    matRef.current.opacity = THREE.MathUtils.lerp(matRef.current.opacity, targetOpacity, dt * 3);
    lerpColor(matRef.current.color, tmpColor.set(cfg.color), dt * 3);
  });

  return (
    <mesh ref={meshRef}>
      <ringGeometry args={[0.9, 1.05, 64]} />
      <meshBasicMaterial
        ref={matRef}
        color={cfg.color}
        transparent
        opacity={0}
        side={THREE.DoubleSide}
        depthWrite={false}
      />
    </mesh>
  );
}

/* ── Ambient glow sprite ── */
function AmbientGlow({ cfg }: { cfg: StateConfig }) {
  const spriteRef = useRef<THREE.Sprite>(null!);

  const map = useMemo(() => {
    const size = 256;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.15, 'rgba(255,255,255,0.6)');
    g.addColorStop(0.4, 'rgba(255,255,255,0.15)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    return new THREE.CanvasTexture(canvas);
  }, []);

  useFrame((s) => {
    if (!spriteRef.current) return;
    const mat = spriteRef.current.material as THREE.SpriteMaterial;
    lerpColor(mat.color, tmpColor.set(cfg.color), 0.04);
    const pulse = 1 + Math.sin(s.clock.elapsedTime * 1.5) * 0.06 * cfg.pulseIntensity;
    spriteRef.current.scale.setScalar(3.5 * pulse);
    mat.opacity = THREE.MathUtils.lerp(mat.opacity, 0.15 * cfg.pulseIntensity, 0.04);
  });

  return (
    <sprite ref={spriteRef}>
      <spriteMaterial map={map} color={cfg.color} transparent opacity={0.12} depthWrite={false} />
    </sprite>
  );
}

/* ── Scene orchestrator ── */
function OrbScene({ state }: { state: AssistantState }) {
  const cfg = STATE_CONFIGS[state];
  const groupRef = useRef<THREE.Group>(null!);

  useFrame((_s, dt) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += dt * 0.06;
    }
  });

  return (
    <group ref={groupRef}>
      <AmbientGlow cfg={cfg} />
      <WireframeGlobe cfg={cfg} state={state} />
      <OrbitalRings cfg={cfg} />
      <GlowingCore cfg={cfg} />
      <OrbParticles cfg={cfg} />
      <ScanRing cfg={cfg} state={state} />
    </group>
  );
}

/* ═══════════════════════════════════
   Public component
   ═══════════════════════════════════ */

interface OrbProps {
  state: AssistantState;
}

export function HolographicOrb({ state }: OrbProps) {
  const [webglFailed, setWebglFailed] = useState(false);

  const handleCreated = useCallback(() => {
    /* Canvas created successfully */
  }, []);

  const handleError = useCallback(() => {
    setWebglFailed(true);
  }, []);

  useEffect(() => {
    try {
      const c = document.createElement('canvas');
      const gl = c.getContext('webgl2') || c.getContext('webgl');
      if (!gl) setWebglFailed(true);
    } catch {
      setWebglFailed(true);
    }
  }, []);

  if (webglFailed) {
    return (
      <div className="holographic-orb holographic-orb--fallback">
        <div className="holographic-orb__fallback-ring" />
        <p className="holographic-orb__fallback-text">
          WebGL unavailable — 3D rendering disabled
        </p>
      </div>
    );
  }

  return (
    <div className="holographic-orb" id="holographic-orb-3d">
      <Canvas
        camera={{ position: [0, 0.15, 3.6], fov: 42 }}
        dpr={[1, 2]}
        gl={{
          antialias: true,
          alpha: true,
          powerPreference: 'high-performance',
          failIfMajorPerformanceCaveat: false,
        }}
        onCreated={handleCreated}
        onError={handleError}
        style={{ background: 'transparent' }}
      >
        <AdaptiveDpr pixelated />
        <ambientLight intensity={0.2} />
        <Suspense fallback={null}>
          <OrbScene state={state} />
        </Suspense>
      </Canvas>
    </div>
  );
}
