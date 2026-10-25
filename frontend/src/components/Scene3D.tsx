import { useEffect, useRef, useState } from 'react'
import { BlueMark } from './BlueMark'

export type SceneNode = { id: string; source: string; score: number | null }
export function Scene3D({
  nodes,
  command = '',
  onSelect,
}: {
  nodes?: SceneNode[]
  command?: string
  onSelect?: (id: string) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const controller = useRef<(command: string) => void>(() => {})
  const selection = useRef(onSelect)
  selection.current = onSelect
  const [ready, setReady] = useState(false)
  useEffect(() => {
    controller.current(command)
  }, [command])
  useEffect(() => {
    const element = host.current!
    let cancelled = false
    let dispose = () => {}
    setReady(false)
    void import('three')
      .then(async (T) => {
        if (cancelled) return
        let renderer: InstanceType<typeof T.WebGLRenderer>
        try {
          renderer = new T.WebGLRenderer({ alpha: true, antialias: true })
        } catch {
          return
        }
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
        renderer.setClearColor(0x000000, 0)
        renderer.outputColorSpace = T.SRGBColorSpace
        const canvas = renderer.domElement
        canvas.setAttribute('aria-hidden', 'true')
        element.appendChild(canvas)
        const scene = new T.Scene()
        const camera = new T.PerspectiveCamera(35, 1, 0.1, 100)
        camera.position.set(0, 0, nodes ? 14 : 7)
        const group = new T.Group()
        scene.add(group, new T.AmbientLight(0xffffff, 2.2))
        const key = new T.DirectionalLight(0xffffff, 5)
        key.position.set(-3, 5, 6)
        const rim = new T.DirectionalLight(0x91baff, 4)
        rim.position.set(4, -2, 2)
        scene.add(key, rim)
        const clickable: InstanceType<typeof T.Mesh>[] = []
        if (!nodes) {
          const shape = new T.Shape()
          shape.moveTo(-0.95, 1.9)
          shape.lineTo(-0.3, 1.58)
          shape.lineTo(-0.3, 0.45)
          shape.bezierCurveTo(1.3, 1.4, 1.75, -0.1, 1, -1.05)
          shape.bezierCurveTo(0.5, -1.65, -0.4, -1.7, -0.95, -1.15)
          shape.closePath()
          const hole = new T.Path()
          hole.moveTo(-0.3, -0.92)
          hole.lineTo(-0.3, -0.1)
          hole.bezierCurveTo(0.65, 0.65, 1.08, -0.65, -0.3, -0.92)
          shape.holes.push(hole)
          const geometry = new T.ExtrudeGeometry(shape, {
            depth: 0.38,
            bevelEnabled: true,
            bevelThickness: 0.07,
            bevelSize: 0.06,
            bevelSegments: 3,
            steps: 1,
            curveSegments: 28,
          })
          geometry.center()
          group.add(
            new T.Mesh(
              geometry,
              new T.MeshPhysicalMaterial({
                color: 0x2455ed,
                metalness: 0.28,
                roughness: 0.16,
                clearcoat: 1,
                clearcoatRoughness: 0.08,
              }),
            ),
          )
          group.rotation.set(-0.13, -0.5, -0.12)
          group.scale.setScalar(0.85)
        } else {
          const sources = [...new Set(nodes.map((n) => n.source))]
          const lineMaterial = new T.LineBasicMaterial({
            color: 0xc0cde3,
            transparent: true,
            opacity: 0.8,
          })
          sources.forEach((source, index) => {
            const angle = (index / sources.length) * Math.PI * 2 - Math.PI / 2
            const center = new T.Vector3(
              Math.cos(angle) * (sources.length > 1 ? 2.5 : 0),
              Math.sin(angle) * (sources.length > 1 ? 2.1 : 0),
              Math.sin(angle * 2) * 0.7,
            )
            const root = new T.Mesh(
              new T.OctahedronGeometry(0.28, 1),
              new T.MeshStandardMaterial({ color: 0x2455ed, metalness: 0.25, roughness: 0.32 }),
            )
            root.position.copy(center)
            group.add(root)
            const members = nodes.filter((n) => n.source === source)
            members.forEach((node, i) => {
              const a = (i / members.length) * Math.PI * 2
              const position = center
                .clone()
                .add(new T.Vector3(Math.cos(a) * 1.05, Math.sin(a) * 1.05, Math.sin(i * 2.3) * 0.7))
              const color =
                node.score === null
                  ? 0x8794aa
                  : node.score >= 60
                    ? 0xb84c5c
                    : node.score >= 30
                      ? 0xb18a4c
                      : 0x49896d
              const sphere = new T.Mesh(
                new T.SphereGeometry(0.105, 16, 12),
                new T.MeshStandardMaterial({ color, roughness: 0.45 }),
              )
              sphere.position.copy(position)
              sphere.userData.id = node.id
              group.add(sphere)
              clickable.push(sphere)
              group.add(
                new T.Line(new T.BufferGeometry().setFromPoints([center, position]), lineMaterial),
              )
            })
          })
        }
        let controls:
          | {
              update: () => void
              dispose: () => void
              addEventListener: (name: 'change', fn: () => void) => void
              reset: () => void
            }
          | undefined
        const render = () => {
          if (!cancelled) renderer.render(scene, camera)
        }
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
        let inView = true
        let last = 0
        const start = performance.now()
        function animate(now: number) {
          if (document.hidden || !inView || reduced.matches || now - last < 33) return
          last = now
          if (!nodes && now - start < 4200)
            group.rotation.y = -0.5 + Math.sin((now - start) / 1400) * 0.32
          else if (!nodes) return
          controls?.update()
          render()
        }
        const resize = new ResizeObserver(() => {
          const width = element.clientWidth,
            height = element.clientHeight
          if (!width || !height) return
          renderer.setSize(width, height)
          camera.aspect = width / height
          camera.updateProjectionMatrix()
          render()
        })
        resize.observe(element)
        const visibility = new IntersectionObserver(([entry]) => {
          inView = entry.isIntersecting
        })
        visibility.observe(element)
        const motionChange = () => {
          renderer.setAnimationLoop(reduced.matches || nodes ? null : animate)
          render()
        }
        const stopAnimation = window.setTimeout(() => renderer.setAnimationLoop(null), 4400)
        reduced.addEventListener('change', motionChange)
        const raycaster = new T.Raycaster()
        const pointer = new T.Vector2()
        let down = { x: 0, y: 0 }
        const pointerDown = (event: PointerEvent) => {
          down = { x: event.clientX, y: event.clientY }
        }
        const pointerUp = (event: PointerEvent) => {
          if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 6) return
          const rect = canvas.getBoundingClientRect()
          pointer.set(
            ((event.clientX - rect.left) / rect.width) * 2 - 1,
            (-(event.clientY - rect.top) / rect.height) * 2 + 1,
          )
          raycaster.setFromCamera(pointer, camera)
          const match = raycaster.intersectObjects(clickable)[0]
          if (match) selection.current?.(match.object.userData.id as string)
        }
        canvas.addEventListener('pointerdown', pointerDown)
        canvas.addEventListener('pointerup', pointerUp)
        canvas.addEventListener('webglcontextlost', (event) => {
          event.preventDefault()
          setReady(false)
        })
        controller.current = (value) => {
          if (value.startsWith('left')) group.rotation.y -= 0.25
          if (value.startsWith('right')) group.rotation.y += 0.25
          if (value.startsWith('in')) camera.position.multiplyScalar(0.87)
          if (value.startsWith('out')) camera.position.multiplyScalar(1.13)
          camera.position.clampLength(5, 25)
          if (value.startsWith('reset')) {
            group.rotation.set(0, 0, 0)
            controls?.reset()
            camera.position.set(0, 0, 14)
          }
          render()
        }
        const cleanup = () => {
          clearTimeout(stopAnimation)
          renderer.setAnimationLoop(null)
          resize.disconnect()
          visibility.disconnect()
          reduced.removeEventListener('change', motionChange)
          canvas.removeEventListener('pointerdown', pointerDown)
          canvas.removeEventListener('pointerup', pointerUp)
          controls?.dispose()
          scene.traverse((object) => {
            if (object instanceof T.Mesh || object instanceof T.Line) {
              object.geometry.dispose()
              const materials = Array.isArray(object.material) ? object.material : [object.material]
              materials.forEach((material) => material.dispose())
            }
          })
          renderer.dispose()
          canvas.remove()
          controller.current = () => {}
        }
        dispose = cleanup
        if (nodes) {
          const { OrbitControls } = await import('three/addons/controls/OrbitControls.js')
          if (cancelled) return
          const orbit = new OrbitControls(camera, canvas)
          orbit.enableDamping = false
          orbit.enablePan = false
          orbit.minDistance = 5
          orbit.maxDistance = 25
          orbit.addEventListener('change', render)
          controls = orbit
        }
        if (cancelled) return
        motionChange()
        render()
        setReady(true)
      })
      .catch(() => {
        if (!cancelled) setReady(false)
      })
    return () => {
      cancelled = true
      dispose()
    }
  }, [nodes])
  return (
    <div
      ref={host}
      className={`scene-3d ${nodes ? 'scene-graph' : 'scene-logo'}`}
      data-ready={ready}
    >
      {!ready && (
        <div className="scene-fallback" aria-hidden="true">
          <BlueMark />
          {nodes && <span>Список связей доступен рядом</span>}
        </div>
      )}
    </div>
  )
}
