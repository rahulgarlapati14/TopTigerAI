const vertexSource = `
  attribute vec3 position;
  attribute vec3 normal;
  uniform float angle;
  uniform float aspect;
  uniform float widthScale;
  varying vec3 surfaceNormal;

  vec3 rotate(vec3 v) {
    float c = cos(angle);
    float s = sin(angle);
    vec3 yaw = vec3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z);
    return vec3(yaw.x, 0.990 * yaw.y - 0.141 * yaw.z, 0.141 * yaw.y + 0.990 * yaw.z);
  }

  void main() {
    vec3 scale = vec3(widthScale, 1.0, widthScale);
    vec3 p = rotate(position * scale - vec3(0.0, 0.91, 0.0));
    float fit = min(1.0, aspect / 0.84) * 0.84;
    gl_Position = vec4(p.x * fit / aspect, p.y * fit, -p.z * 0.4, 1.0);
    surfaceNormal = rotate(normal / scale);
  }
`;

const fragmentSource = `
  precision mediump float;
  uniform vec3 finish;
  varying vec3 surfaceNormal;

  void main() {
    vec3 n = normalize(surfaceNormal);
    float key = max(dot(n, normalize(vec3(-0.5, 0.9, 0.75))), 0.0);
    float rim = max(dot(n, normalize(vec3(0.9, 0.2, -0.65))), 0.0);
    vec3 color = finish * (0.26 + 0.68 * key) + vec3(0.24, 0.15, 0.09) * rim;
    gl_FragColor = vec4(color, 1.0);
  }
`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader));
  }
  return shader;
}

export async function createTiger(canvas) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true });
  if (!gl || !gl.getExtension('OES_element_index_uint')) {
    throw new Error('WebGL with 32-bit mesh indices is required.');
  }

  const response = await fetch('/static/tiger.glb');
  if (!response.ok) throw new Error('Unable to load tiger model.');
  const model = await response.arrayBuffer();
  const view = new DataView(model);
  const jsonLength = view.getUint32(12, true);
  const asset = JSON.parse(new TextDecoder().decode(new Uint8Array(model, 20, jsonLength)));
  const byteStart = 28 + jsonLength;
  const mesh = asset.meshes[0].primitives[0];

  // This asset packs one mesh with float positions and normals and unsigned 32-bit indices.
  function upload(accessorIndex, target, ArrayType, components) {
    const accessor = asset.accessors[accessorIndex];
    const bufferView = asset.bufferViews[accessor.bufferView];
    const offset = byteStart + (bufferView.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
    gl.bindBuffer(target, gl.createBuffer());
    gl.bufferData(target, new ArrayType(model, offset, accessor.count * components), gl.STATIC_DRAW);
    return accessor.count;
  }

  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertexSource));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragmentSource));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program));
  }
  gl.useProgram(program);

  for (const [name, source] of [['position', 'POSITION'], ['normal', 'NORMAL']]) {
    upload(mesh.attributes[source], gl.ARRAY_BUFFER, Float32Array, 3);
    const location = gl.getAttribLocation(program, name);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0);
  }

  const indices = upload(mesh.indices, gl.ELEMENT_ARRAY_BUFFER, Uint32Array, 1);
  const angle = gl.getUniformLocation(program, 'angle');
  const aspect = gl.getUniformLocation(program, 'aspect');
  const finish = gl.getUniformLocation(program, 'finish');
  const widthScale = gl.getUniformLocation(program, 'widthScale');
  gl.enable(gl.DEPTH_TEST);
  let rotation = 0.22;
  let color;
  let modelWidth;
  let drag;

  function draw(selectedColor, selectedWidth) {
    color = selectedColor;
    modelWidth = selectedWidth;
    const { clientWidth, clientHeight } = canvas;
    if (!clientWidth || !clientHeight) return;
    const density = Math.min(window.devicePixelRatio, 2);
    const width = Math.round(clientWidth * density);
    const height = Math.round(clientHeight * density);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    gl.viewport(0, 0, width, height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.uniform1f(angle, rotation);
    gl.uniform1f(aspect, width / height);
    gl.uniform1f(widthScale, modelWidth);
    gl.uniform3fv(finish, color);
    gl.drawElements(gl.TRIANGLES, indices, gl.UNSIGNED_INT, 0);
  }

  canvas.addEventListener('pointerdown', event => {
    if (!event.isPrimary || event.button !== 0) return;
    drag = event.clientX;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!event.isPrimary || drag === undefined) return;
    rotation += (event.clientX - drag) * 0.014;
    drag = event.clientX;
    draw(color, modelWidth);
  });
  canvas.addEventListener('lostpointercapture', () => { drag = undefined; });
  return { draw };
}
