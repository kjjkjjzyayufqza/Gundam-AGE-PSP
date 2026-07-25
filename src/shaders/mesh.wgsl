// Preview shading for AGE meshes.
//
// Three programs share one uniform block (group 0):
//   vs_main + fs_solid     - textured/untextured lambert with a small specular
//   vs_main + fs_wireframe - flat dark edges for the LineList overlay
//   vs_line + fs_line      - pass-through coloured lines for the grid and axes
//
// `use_texture` is a uniform, not a per-draw push constant: the renderer keeps
// two uniform buffers that differ only in this flag and switches bind group 0
// per part, so a single render pass can mix textured and untextured meshes.

struct Uniforms {
    mvp: mat4x4<f32>,
    model: mat4x4<f32>,
    light_dir: vec3<f32>,
    ambient: f32,
    camera_pos: vec3<f32>,
    use_texture: f32,
};

@group(0) @binding(0) var<uniform> u: Uniforms;
@group(1) @binding(0) var diffuse_texture: texture_2d<f32>;
@group(1) @binding(1) var diffuse_sampler: sampler;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) world_normal: vec3<f32>,
    @location(1) uv: vec2<f32>,
    @location(2) world_pos: vec3<f32>,
};

@vertex
fn vs_main(in: VertexInput) -> VertexOutput {
    var out: VertexOutput;
    out.clip_position = u.mvp * vec4(in.position, 1.0);
    out.world_normal = (u.model * vec4(in.normal, 0.0)).xyz;
    out.uv = in.uv;
    out.world_pos = (u.model * vec4(in.position, 1.0)).xyz;
    return out;
}

@fragment
fn fs_solid(in: VertexOutput) -> @location(0) vec4<f32> {
    let view_dir = normalize(u.camera_pos - in.world_pos);

    // Faces are drawn with culling disabled because PSP strip winding is not
    // consistent across archives, so flip the normal toward the viewer instead
    // of letting back faces render black.
    var n = normalize(in.world_normal);
    if dot(n, view_dir) < 0.0 {
        n = -n;
    }

    let light = normalize(u.light_dir);
    let diffuse = max(dot(n, light), 0.0);
    let lighting = u.ambient + (1.0 - u.ambient) * diffuse;

    var base_color = vec3<f32>(0.7, 0.7, 0.75);
    var alpha = 1.0;
    if u.use_texture > 0.5 {
        let sampled = textureSample(diffuse_texture, diffuse_sampler, in.uv);
        base_color = sampled.rgb;
        alpha = sampled.a;
    }

    let half_dir = normalize(light + view_dir);
    let spec = pow(max(dot(n, half_dir), 0.0), 32.0) * 0.3;

    let color = base_color * lighting + vec3<f32>(spec);
    return vec4(color, alpha);
}

@fragment
fn fs_wireframe(in: VertexOutput) -> @location(0) vec4<f32> {
    return vec4(0.02, 0.02, 0.03, 0.55);
}

struct LineVertex {
    @location(0) position: vec3<f32>,
    @location(1) color: vec4<f32>,
};

struct LineOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) color: vec4<f32>,
};

@vertex
fn vs_line(in: LineVertex) -> LineOutput {
    var out: LineOutput;
    out.clip_position = u.mvp * vec4(in.position, 1.0);
    out.color = in.color;
    return out;
}

@fragment
fn fs_line(in: LineOutput) -> @location(0) vec4<f32> {
    return in.color;
}
