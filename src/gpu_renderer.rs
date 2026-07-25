//! wgpu offscreen renderer for the 3D preview.
//!
//! INTERFACE CONTRACT - the signatures below are fixed. Implementations may add
//! private fields and helpers but must not change these public shapes.
//!
//! Unlike the gvg_np renderer this was adapted from, an AGE scene binds a
//! *different* texture per mesh, so the scene is uploaded as one vertex/index
//! buffer plus a list of parts, and each part is drawn with its own bind group.
//!
//! Two conventions the UI layer needs to know about:
//!
//! * `GpuScene::parts` holds **exactly one part per `Scene::meshes` entry, in
//!   the same order**. Meshes that carry no drawable geometry get a part with
//!   `index_count == 0` instead of being dropped, so the `visible` slice the UI
//!   passes to [`GpuRenderer::render`] can stay indexed by scene mesh order.
//! * [`GpuScene::bounds`] and [`GpuScene::focus_target`] are reported in the
//!   space the camera works in, i.e. *after* the negated-X display transform.
//!   Feeding them straight into `PreviewCamera::frame_bounds_with_target`
//!   therefore frames off-centre archives (maps) correctly.

use crate::render::{PreviewBounds, PreviewCamera};
use crate::theme;
use eframe::egui;
use eframe::egui_wgpu::wgpu;
use eframe::egui_wgpu::wgpu::util::DeviceExt;

const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;
const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth24Plus;
const LIGHT_DIR: [f32; 3] = [0.5, 0.8, 0.6];
const AMBIENT: f32 = 0.3;
/// Upper bound on grid line pairs per axis, so a pathological extent/step ratio
/// cannot allocate an enormous vertex buffer.
const MAX_GRID_DIVISIONS: i32 = 512;

#[derive(Clone, Copy, Debug)]
pub struct RenderOptions {
    pub show_wireframe: bool,
    pub show_grid: bool,
    pub show_axes: bool,
    pub show_textures: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct GpuRenderStats {
    pub total_ms: f64,
    pub viewport_size: [u32; 2],
    pub draw_calls: u32,
}

/// One drawable run of indices sharing a single texture binding.
pub struct GpuPart {
    pub index_start: u32,
    pub index_count: u32,
    /// Index into the scene's uploaded textures, when the mesh had a binding.
    pub texture: Option<usize>,
}

/// A whole archive uploaded to the GPU.
pub struct GpuScene {
    vertex_buffer: wgpu::Buffer,
    index_buffer: wgpu::Buffer,
    wireframe_index_buffer: wgpu::Buffer,
    wireframe_index_count: u32,
    /// One entry per `Scene::meshes` entry, in scene order.
    parts: Vec<GpuPart>,
    /// One entry per `Scene::textures` entry, in scene order.
    textures: Vec<wgpu::BindGroup>,
    vertex_count: u32,
    index_count: u32,
    bounds: PreviewBounds,
    focus_target: [f32; 3],
}

impl GpuScene {
    pub fn bounds(&self) -> PreviewBounds {
        self.bounds
    }

    pub fn focus_target(&self) -> [f32; 3] {
        self.focus_target
    }

    pub fn vertex_count(&self) -> u32 {
        self.vertex_count
    }

    pub fn triangle_count(&self) -> u32 {
        self.index_count / 3
    }

    pub fn part_count(&self) -> usize {
        self.parts.len()
    }
}

pub struct GpuRenderer {
    solid_pipeline: wgpu::RenderPipeline,
    wireframe_pipeline: wgpu::RenderPipeline,
    line_pipeline: wgpu::RenderPipeline,
    /// Uniforms with `use_texture = 1`, bound for parts that sample a texture.
    textured_uniform_buffer: wgpu::Buffer,
    textured_uniform_bind_group: wgpu::BindGroup,
    /// Uniforms with `use_texture = 0`, bound for untextured parts and lines.
    plain_uniform_buffer: wgpu::Buffer,
    plain_uniform_bind_group: wgpu::BindGroup,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    default_texture_bind_group: wgpu::BindGroup,
    sampler: wgpu::Sampler,
    color_view: Option<wgpu::TextureView>,
    depth_view: Option<wgpu::TextureView>,
    viewport_size: [u32; 2],
    egui_texture_id: Option<egui::TextureId>,
    axis_lines: GpuLineMesh,
    grid_lines: GpuLineMesh,
}

impl GpuRenderer {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("age_mesh_shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("shaders/mesh.wgsl").into()),
        });

        let uniform_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("uniform_bgl"),
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                }],
            });

        let (textured_uniform_buffer, textured_uniform_bind_group) = create_uniform_slot(
            device,
            &uniform_bind_group_layout,
            "textured",
            Uniforms::identity(true),
        );
        let (plain_uniform_buffer, plain_uniform_bind_group) = create_uniform_slot(
            device,
            &uniform_bind_group_layout,
            "plain",
            Uniforms::identity(false),
        );

        let texture_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("texture_bgl"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            multisampled: false,
                            view_dimension: wgpu::TextureViewDimension::D2,
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                        count: None,
                    },
                ],
            });

        // Game UVs routinely run outside 0..1, so tile instead of clamping.
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("mesh_sampler"),
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::Repeat,
            address_mode_w: wgpu::AddressMode::Repeat,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        let default_texture_bind_group = create_white_texture_bind_group(
            device,
            queue,
            &texture_bind_group_layout,
            &sampler,
        );

        let mesh_vertex_layout = wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<GpuVertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &[
                wgpu::VertexAttribute {
                    offset: 0,
                    shader_location: 0,
                    format: wgpu::VertexFormat::Float32x3,
                },
                wgpu::VertexAttribute {
                    offset: 12,
                    shader_location: 1,
                    format: wgpu::VertexFormat::Float32x3,
                },
                wgpu::VertexAttribute {
                    offset: 24,
                    shader_location: 2,
                    format: wgpu::VertexFormat::Float32x2,
                },
            ],
        };

        let line_vertex_layout = wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<LineVertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &[
                wgpu::VertexAttribute {
                    offset: 0,
                    shader_location: 0,
                    format: wgpu::VertexFormat::Float32x3,
                },
                wgpu::VertexAttribute {
                    offset: 12,
                    shader_location: 1,
                    format: wgpu::VertexFormat::Float32x4,
                },
            ],
        };

        let mesh_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("mesh_pipeline_layout"),
            bind_group_layouts: &[&uniform_bind_group_layout, &texture_bind_group_layout],
            push_constant_ranges: &[],
        });

        let line_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("line_pipeline_layout"),
            bind_group_layouts: &[&uniform_bind_group_layout],
            push_constant_ranges: &[],
        });

        let depth_stencil = Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: true,
            depth_compare: wgpu::CompareFunction::Less,
            stencil: wgpu::StencilState::default(),
            bias: wgpu::DepthBiasState::default(),
        });

        let color_target = Some(wgpu::ColorTargetState {
            format: COLOR_FORMAT,
            blend: Some(wgpu::BlendState::ALPHA_BLENDING),
            write_mask: wgpu::ColorWrites::ALL,
        });

        let solid_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("solid_pipeline"),
            layout: Some(&mesh_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_main"),
                buffers: &[mesh_vertex_layout.clone()],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_solid"),
                targets: &[color_target.clone()],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                // PSP strip winding is not consistent across archives.
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: depth_stencil.clone(),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        let wireframe_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("wireframe_pipeline"),
            layout: Some(&mesh_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_main"),
                buffers: &[mesh_vertex_layout],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_wireframe"),
                targets: &[color_target.clone()],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::LineList,
                ..Default::default()
            },
            // Pull the edges toward the viewer so they are not z-fought by the
            // faces they belong to, and never occlude solid geometry.
            depth_stencil: Some(wgpu::DepthStencilState {
                format: DEPTH_FORMAT,
                depth_write_enabled: false,
                depth_compare: wgpu::CompareFunction::LessEqual,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState {
                    constant: -2,
                    slope_scale: -1.0,
                    clamp: 0.0,
                },
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        let line_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("line_pipeline"),
            layout: Some(&line_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_line"),
                buffers: &[line_vertex_layout],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_line"),
                targets: &[color_target],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::LineList,
                ..Default::default()
            },
            depth_stencil,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        let axis_lines = create_axis_lines(device);
        let grid_lines = create_ground_grid(device, 50.0, 5.0);

        Self {
            solid_pipeline,
            wireframe_pipeline,
            line_pipeline,
            textured_uniform_buffer,
            textured_uniform_bind_group,
            plain_uniform_buffer,
            plain_uniform_bind_group,
            texture_bind_group_layout,
            default_texture_bind_group,
            sampler,
            color_view: None,
            depth_view: None,
            viewport_size: [0, 0],
            egui_texture_id: None,
            axis_lines,
            grid_lines,
        }
    }

    /// Upload every mesh of a decoded scene plus its bound textures.
    /// Returns `None` when the scene has no drawable geometry.
    pub fn upload_scene(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        scene: &crate::scene::Scene,
    ) -> Option<GpuScene> {
        let geometry = build_geometry(&scene.meshes);
        if geometry.vertices.is_empty() || geometry.indices.is_empty() {
            return None;
        }

        let wireframe_indices = build_wireframe_indices(&geometry.indices);

        let vertex_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("scene_vb"),
            contents: bytemuck::cast_slice(&geometry.vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let index_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("scene_ib"),
            contents: bytemuck::cast_slice(&geometry.indices),
            usage: wgpu::BufferUsages::INDEX,
        });
        let wireframe_index_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("scene_wire_ib"),
            contents: bytemuck::cast_slice(&wireframe_indices),
            usage: wgpu::BufferUsages::INDEX,
        });

        let textures = scene
            .textures
            .iter()
            .map(|entry| {
                self.upload_texture(
                    device,
                    queue,
                    &entry.texture.rgba_bytes(),
                    entry.texture.width,
                    entry.texture.height,
                )
            })
            .collect();

        Some(GpuScene {
            vertex_buffer,
            index_buffer,
            wireframe_index_buffer,
            wireframe_index_count: wireframe_indices.len() as u32,
            parts: geometry.parts,
            textures,
            vertex_count: geometry.vertices.len() as u32,
            index_count: geometry.indices.len() as u32,
            bounds: geometry.bounds,
            focus_target: geometry.focus_target,
        })
    }

    /// (Re)create the offscreen colour/depth targets and register the egui texture.
    pub fn ensure_viewport(
        &mut self,
        device: &wgpu::Device,
        egui_renderer: &mut eframe::egui_wgpu::Renderer,
        width: u32,
        height: u32,
    ) {
        let w = width.max(1);
        let h = height.max(1);
        if self.viewport_size == [w, h] && self.egui_texture_id.is_some() {
            return;
        }
        self.viewport_size = [w, h];

        let size = wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: 1,
        };

        // Views keep their parent texture alive, so only the views are stored.
        let color_view = device
            .create_texture(&wgpu::TextureDescriptor {
                label: Some("offscreen_color"),
                size,
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: COLOR_FORMAT,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            })
            .create_view(&wgpu::TextureViewDescriptor::default());

        let depth_view = device
            .create_texture(&wgpu::TextureDescriptor {
                label: Some("offscreen_depth"),
                size,
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: DEPTH_FORMAT,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                view_formats: &[],
            })
            .create_view(&wgpu::TextureViewDescriptor::default());

        // Free the previous registration first; leaking it would grow GPU
        // memory on every resize.
        if let Some(old) = self.egui_texture_id.take() {
            egui_renderer.free_texture(&old);
        }
        let texture_id =
            egui_renderer.register_native_texture(device, &color_view, wgpu::FilterMode::Linear);

        self.color_view = Some(color_view);
        self.depth_view = Some(depth_view);
        self.egui_texture_id = Some(texture_id);
    }

    pub fn egui_texture_id(&self) -> Option<egui::TextureId> {
        self.egui_texture_id
    }

    pub fn update_grid(&mut self, device: &wgpu::Device, extent: f32, step: f32) {
        self.grid_lines = create_ground_grid(device, extent, step);
    }

    /// Draw the scene. `visible[i]` gates part `i`; a shorter slice means visible.
    /// Passing `None` for the scene renders only the grid and axes.
    pub fn render(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        camera: &PreviewCamera,
        scene: Option<&GpuScene>,
        visible: &[bool],
        options: RenderOptions,
    ) -> Option<GpuRenderStats> {
        let started = std::time::Instant::now();
        let color_view = self.color_view.as_ref()?;
        let depth_view = self.depth_view.as_ref()?;

        let [vw, vh] = self.viewport_size;
        // The only per-part uniform is `use_texture`, so instead of rewriting one
        // buffer between draws (queue writes are all applied before the pass runs,
        // so the last write would win) both variants are uploaded up front and
        // selected by swapping bind group 0.
        let uniforms = build_uniforms(camera, vw, vh, true);
        queue.write_buffer(
            &self.textured_uniform_buffer,
            0,
            bytemuck::cast_slice(&[uniforms]),
        );
        queue.write_buffer(
            &self.plain_uniform_buffer,
            0,
            bytemuck::cast_slice(&[Uniforms {
                use_texture: 0.0,
                ..uniforms
            }]),
        );

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("scene_render"),
        });
        let mut draw_calls = 0u32;

        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("scene_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: color_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: theme::VIEWPORT_CLEAR[0],
                            g: theme::VIEWPORT_CLEAR[1],
                            b: theme::VIEWPORT_CLEAR[2],
                            a: 1.0,
                        }),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                ..Default::default()
            });

            if let Some(scene) = scene {
                pass.set_pipeline(&self.solid_pipeline);
                pass.set_vertex_buffer(0, scene.vertex_buffer.slice(..));
                pass.set_index_buffer(scene.index_buffer.slice(..), wgpu::IndexFormat::Uint32);

                for (index, part) in scene.parts.iter().enumerate() {
                    if part.index_count == 0 || !part_is_visible(visible, index) {
                        continue;
                    }
                    let texture = if options.show_textures {
                        part.texture.and_then(|t| scene.textures.get(t))
                    } else {
                        None
                    };
                    match texture {
                        Some(bind_group) => {
                            pass.set_bind_group(0, &self.textured_uniform_bind_group, &[]);
                            pass.set_bind_group(1, bind_group, &[]);
                        }
                        None => {
                            pass.set_bind_group(0, &self.plain_uniform_bind_group, &[]);
                            pass.set_bind_group(1, &self.default_texture_bind_group, &[]);
                        }
                    }
                    pass.draw_indexed(
                        part.index_start..part.index_start + part.index_count,
                        0,
                        0..1,
                    );
                    draw_calls += 1;
                }

                if options.show_wireframe && scene.wireframe_index_count > 0 {
                    pass.set_pipeline(&self.wireframe_pipeline);
                    pass.set_bind_group(0, &self.plain_uniform_bind_group, &[]);
                    pass.set_bind_group(1, &self.default_texture_bind_group, &[]);
                    pass.set_vertex_buffer(0, scene.vertex_buffer.slice(..));
                    pass.set_index_buffer(
                        scene.wireframe_index_buffer.slice(..),
                        wgpu::IndexFormat::Uint32,
                    );
                    for (index, part) in scene.parts.iter().enumerate() {
                        if part.index_count == 0 || !part_is_visible(visible, index) {
                            continue;
                        }
                        let (start, end) =
                            wireframe_range(part, scene.wireframe_index_count);
                        if start >= end {
                            continue;
                        }
                        pass.draw_indexed(start..end, 0, 0..1);
                        draw_calls += 1;
                    }
                }
            }

            if options.show_grid && self.grid_lines.vertex_count > 0 {
                pass.set_pipeline(&self.line_pipeline);
                pass.set_bind_group(0, &self.plain_uniform_bind_group, &[]);
                pass.set_vertex_buffer(0, self.grid_lines.vertex_buffer.slice(..));
                pass.draw(0..self.grid_lines.vertex_count, 0..1);
                draw_calls += 1;
            }

            if options.show_axes && self.axis_lines.vertex_count > 0 {
                pass.set_pipeline(&self.line_pipeline);
                pass.set_bind_group(0, &self.plain_uniform_bind_group, &[]);
                pass.set_vertex_buffer(0, self.axis_lines.vertex_buffer.slice(..));
                pass.draw(0..self.axis_lines.vertex_count, 0..1);
                draw_calls += 1;
            }
        }

        queue.submit(std::iter::once(encoder.finish()));

        Some(GpuRenderStats {
            total_ms: started.elapsed().as_secs_f64() * 1000.0,
            viewport_size: self.viewport_size,
            draw_calls,
        })
    }

    fn upload_texture(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        rgba: &[u8],
        width: u32,
        height: u32,
    ) -> wgpu::BindGroup {
        let width = width.max(1);
        let height = height.max(1);
        let expected = width as usize * height as usize * 4;
        // A short/garbled decode must not abort the upload of the rest of the
        // archive, so pad (or trim) to the size the descriptor promises.
        let mut pixels = rgba.to_vec();
        pixels.resize(expected, 0);

        let texture = device.create_texture_with_data(
            queue,
            &wgpu::TextureDescriptor {
                label: Some("scene_texture"),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: COLOR_FORMAT,
                usage: wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            },
            wgpu::util::TextureDataOrder::LayerMajor,
            &pixels,
        );
        let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("scene_texture_bg"),
            layout: &self.texture_bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
            ],
        })
    }
}

// ---------------------------------------------------------------------------
// GPU data layout
// ---------------------------------------------------------------------------

#[repr(C)]
#[derive(Copy, Clone, Debug, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
struct GpuVertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
}

#[repr(C)]
#[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
struct LineVertex {
    position: [f32; 3],
    color: [f32; 4],
}

#[repr(C)]
#[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
struct Uniforms {
    mvp: [[f32; 4]; 4],
    model: [[f32; 4]; 4],
    light_dir: [f32; 3],
    ambient: f32,
    camera_pos: [f32; 3],
    use_texture: f32,
}

impl Uniforms {
    fn identity(use_texture: bool) -> Self {
        Self {
            mvp: mat4_identity(),
            model: mat4_identity(),
            light_dir: LIGHT_DIR,
            ambient: AMBIENT,
            camera_pos: [0.0, 0.0, 5.0],
            use_texture: if use_texture { 1.0 } else { 0.0 },
        }
    }
}

struct GpuLineMesh {
    vertex_buffer: wgpu::Buffer,
    vertex_count: u32,
}

// ---------------------------------------------------------------------------
// CPU-side scene assembly (unit tested; no device required)
// ---------------------------------------------------------------------------

struct SceneGeometry {
    vertices: Vec<GpuVertex>,
    indices: Vec<u32>,
    parts: Vec<GpuPart>,
    bounds: PreviewBounds,
    focus_target: [f32; 3],
}

/// Model space -> display space. The preview mirrors X so the game's handedness
/// reads correctly on screen; bounds and focus targets are reported in this
/// space because that is where the camera lives.
fn to_display_space(p: [f32; 3]) -> [f32; 3] {
    [-p[0], p[1], p[2]]
}

/// Concatenate every mesh into one vertex/index pair, emitting exactly one part
/// per scene mesh so caller-side `visible` slices stay aligned. Meshes without
/// drawable geometry contribute a zero-length part.
fn build_geometry(meshes: &[crate::scene::SceneMesh]) -> SceneGeometry {
    let mut vertices: Vec<GpuVertex> = Vec::new();
    let mut indices: Vec<u32> = Vec::new();
    let mut parts: Vec<GpuPart> = Vec::with_capacity(meshes.len());
    let mut min = [f32::INFINITY; 3];
    let mut max = [f32::NEG_INFINITY; 3];
    let mut sum = [0.0f64; 3];

    for entry in meshes {
        let mesh = &entry.mesh;
        let index_start = indices.len() as u32;

        if mesh.positions.is_empty() || mesh.faces.is_empty() {
            parts.push(GpuPart {
                index_start,
                index_count: 0,
                texture: entry.texture_index,
            });
            continue;
        }

        let base = vertices.len() as u32;
        let has_uvs = mesh.has_uvs && !mesh.uvs.is_empty();
        let has_normals = mesh.normals.len() == mesh.positions.len();

        for (i, position) in mesh.positions.iter().enumerate() {
            let display = to_display_space(*position);
            for axis in 0..3 {
                min[axis] = min[axis].min(display[axis]);
                max[axis] = max[axis].max(display[axis]);
                sum[axis] += display[axis] as f64;
            }
            vertices.push(GpuVertex {
                position: *position,
                normal: if has_normals {
                    mesh.normals[i]
                } else {
                    [0.0, 1.0, 0.0]
                },
                uv: if has_uvs {
                    mesh.uvs.get(i).copied().unwrap_or([0.0, 0.0])
                } else {
                    [0.0, 0.0]
                },
            });
        }

        let limit = mesh.positions.len() as u32;
        for face in &mesh.faces {
            // Guard against malformed archives: an out-of-range index would read
            // another mesh's vertices (or past the buffer) on the GPU.
            if face.iter().any(|i| *i >= limit) {
                continue;
            }
            indices.extend_from_slice(&[base + face[0], base + face[1], base + face[2]]);
        }

        parts.push(GpuPart {
            index_start,
            index_count: indices.len() as u32 - index_start,
            texture: entry.texture_index,
        });
    }

    let (bounds, focus_target) = if vertices.is_empty() {
        (PreviewBounds::new([0.0; 3], [0.0; 3]), [0.0; 3])
    } else {
        let count = vertices.len() as f64;
        (
            PreviewBounds::new(min, max),
            [
                (sum[0] / count) as f32,
                (sum[1] / count) as f32,
                (sum[2] / count) as f32,
            ],
        )
    };

    SceneGeometry {
        vertices,
        indices,
        parts,
        bounds,
        focus_target,
    }
}

/// Three edges per triangle, reusing the triangle indices.
fn build_wireframe_indices(triangle_indices: &[u32]) -> Vec<u32> {
    let mut lines = Vec::with_capacity((triangle_indices.len() / 3) * 6);
    for tri in triangle_indices.chunks_exact(3) {
        lines.extend_from_slice(&[tri[0], tri[1], tri[1], tri[2], tri[2], tri[0]]);
    }
    lines
}

/// Wireframe indices are emitted 6-per-triangle in triangle order, so a part's
/// edge range is just its triangle range doubled.
fn wireframe_range(part: &GpuPart, wireframe_index_count: u32) -> (u32, u32) {
    let start = part.index_start.saturating_mul(2).min(wireframe_index_count);
    let end = part
        .index_start
        .saturating_add(part.index_count)
        .saturating_mul(2)
        .min(wireframe_index_count);
    (start, end)
}

/// A `visible` slice shorter than the part list means "visible" for the rest.
fn part_is_visible(visible: &[bool], index: usize) -> bool {
    visible.get(index).copied().unwrap_or(true)
}

// ---------------------------------------------------------------------------
// Static GPU resources
// ---------------------------------------------------------------------------

fn create_uniform_slot(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    label: &str,
    initial: Uniforms,
) -> (wgpu::Buffer, wgpu::BindGroup) {
    let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(&format!("{label}_uniforms")),
        contents: bytemuck::cast_slice(&[initial]),
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
    });
    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some(&format!("{label}_uniform_bg")),
        layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: buffer.as_entire_binding(),
        }],
    });
    (buffer, bind_group)
}

fn create_white_texture_bind_group(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    layout: &wgpu::BindGroupLayout,
    sampler: &wgpu::Sampler,
) -> wgpu::BindGroup {
    let texture = device.create_texture_with_data(
        queue,
        &wgpu::TextureDescriptor {
            label: Some("white_1x1"),
            size: wgpu::Extent3d {
                width: 1,
                height: 1,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COLOR_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        },
        wgpu::util::TextureDataOrder::LayerMajor,
        &[255, 255, 255, 255],
    );
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("white_texture_bg"),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(sampler),
            },
        ],
    })
}

fn create_axis_lines(device: &wgpu::Device) -> GpuLineMesh {
    let len = 1.0f32;
    let verts = [
        LineVertex {
            position: [0.0, 0.0, 0.0],
            color: [0.85, 0.28, 0.28, 1.0],
        },
        LineVertex {
            position: [len, 0.0, 0.0],
            color: [0.85, 0.28, 0.28, 1.0],
        },
        LineVertex {
            position: [0.0, 0.0, 0.0],
            color: [0.40, 0.78, 0.42, 1.0],
        },
        LineVertex {
            position: [0.0, len, 0.0],
            color: [0.40, 0.78, 0.42, 1.0],
        },
        LineVertex {
            position: [0.0, 0.0, 0.0],
            color: [0.34, 0.52, 0.88, 1.0],
        },
        LineVertex {
            position: [0.0, 0.0, len],
            color: [0.34, 0.52, 0.88, 1.0],
        },
    ];
    let vertex_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("axis_vb"),
        contents: bytemuck::cast_slice(&verts),
        usage: wgpu::BufferUsages::VERTEX,
    });
    GpuLineMesh {
        vertex_buffer,
        vertex_count: verts.len() as u32,
    }
}

fn create_ground_grid(device: &wgpu::Device, extent: f32, step: f32) -> GpuLineMesh {
    let extent = if extent.is_finite() && extent > 0.0 {
        extent
    } else {
        50.0
    };
    let step = if step.is_finite() && step > 0.0 {
        step
    } else {
        extent / 10.0
    };
    let divisions = ((extent / step) as i32).clamp(1, MAX_GRID_DIVISIONS);

    let major = [0.24, 0.25, 0.27, 1.0];
    let minor = [0.155, 0.165, 0.175, 1.0];
    let mut verts = Vec::with_capacity((divisions as usize * 2 + 1) * 4);
    for i in -divisions..=divisions {
        let offset = i as f32 * step;
        let color = if i % 5 == 0 { major } else { minor };
        verts.push(LineVertex {
            position: [offset, 0.0, -extent],
            color,
        });
        verts.push(LineVertex {
            position: [offset, 0.0, extent],
            color,
        });
        verts.push(LineVertex {
            position: [-extent, 0.0, offset],
            color,
        });
        verts.push(LineVertex {
            position: [extent, 0.0, offset],
            color,
        });
    }
    let vertex_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("grid_vb"),
        contents: bytemuck::cast_slice(&verts),
        usage: wgpu::BufferUsages::VERTEX,
    });
    GpuLineMesh {
        vertex_buffer,
        vertex_count: verts.len() as u32,
    }
}

// ---------------------------------------------------------------------------
// Camera math. Matrices are column-major, matching WGSL's `mat * vec` order.
// ---------------------------------------------------------------------------

fn build_uniforms(camera: &PreviewCamera, vw: u32, vh: u32, use_texture: bool) -> Uniforms {
    let aspect = vw.max(1) as f32 / vh.max(1) as f32;
    let view = look_at(camera);
    let proj = perspective(camera.fov_y_radians, aspect, camera.near, camera.far);
    // Mirror X so the game's handedness displays correctly.
    let mut model = mat4_identity();
    model[0][0] = -1.0;
    let mvp = mat4_mul(model, mat4_mul(view, proj));

    Uniforms {
        mvp,
        model,
        light_dir: LIGHT_DIR,
        ambient: AMBIENT,
        camera_pos: camera.eye(),
        use_texture: if use_texture { 1.0 } else { 0.0 },
    }
}

fn mat4_identity() -> [[f32; 4]; 4] {
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
}

/// `mat4_mul(a, b)` applies `a` first, then `b` (i.e. the column-major product
/// `b * a`), so `mat4_mul(model, mat4_mul(view, proj))` is a usable MVP.
fn mat4_mul(a: [[f32; 4]; 4], b: [[f32; 4]; 4]) -> [[f32; 4]; 4] {
    let mut r = [[0.0f32; 4]; 4];
    for i in 0..4 {
        for j in 0..4 {
            r[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j];
        }
    }
    r
}

fn look_at(camera: &PreviewCamera) -> [[f32; 4]; 4] {
    let f = normalize3(camera.forward());
    let eye = camera.eye();
    let r = normalize3(cross3([0.0, 1.0, 0.0], f));
    let u = cross3(f, r);

    // Camera looks along -Z in view space, matching the perspective matrix's
    // `w_clip = -z_view` expectation.
    [
        [r[0], u[0], -f[0], 0.0],
        [r[1], u[1], -f[1], 0.0],
        [r[2], u[2], -f[2], 0.0],
        [-dot3(r, eye), -dot3(u, eye), dot3(f, eye), 1.0],
    ]
}

fn perspective(fov_y: f32, aspect: f32, near: f32, far: f32) -> [[f32; 4]; 4] {
    let f = 1.0 / (fov_y * 0.5).tan();
    let range_inv = 1.0 / (near - far);
    [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, far * range_inv, -1.0],
        [0.0, 0.0, near * far * range_inv, 0.0],
    ]
}

fn dot3(a: [f32; 3], b: [f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

fn cross3(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn normalize3(v: [f32; 3]) -> [f32; 3] {
    let len = dot3(v, v).sqrt();
    if len <= f32::EPSILON {
        [0.0; 3]
    } else {
        [v[0] / len, v[1] / len, v[2] / len]
    }
}

/// Grid extent and step sized to the model so unit-scale and world-scale
/// archives both get a readable ground plane.
pub fn compute_grid_params(bounds: Option<&PreviewBounds>) -> (f32, f32) {
    match bounds {
        Some(b) => {
            let max_dim = b.max_dimension();
            if max_dim <= f32::EPSILON {
                return (10.0, 1.0);
            }
            let extent = max_dim * 1.5;
            let step = extent / 20.0;
            (extent, step)
        }
        None => (50.0, 5.0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::material::BindConfidence;
    use crate::scene::SceneMesh;
    use crate::xmpr;

    fn mesh(
        positions: Vec<[f32; 3]>,
        uvs: Vec<[f32; 2]>,
        normals: Vec<[f32; 3]>,
        faces: Vec<[u32; 3]>,
    ) -> xmpr::Mesh {
        let has_uvs = !uvs.is_empty();
        xmpr::Mesh {
            source: "000.prm".to_string(),
            name: "m".to_string(),
            material: "DefaultLib.m".to_string(),
            positions,
            uvs,
            normals,
            faces,
            has_uvs,
            stride: 0,
            position_format: xmpr::PositionFormat::Float32x3,
            uv_format: xmpr::UvFormat::Absent,
            attributes: Vec::new(),
            node_hashes: Vec::new(),
            raw_weights: Vec::new(),
            attribute_method: crate::level5::Method::None,
            vertex_method: crate::level5::Method::None,
            primitive_type: 2,
            declared_face_count: 0,
            dropped_degenerate_faces: 0,
            bounds_min: [0.0; 3],
            bounds_max: [0.0; 3],
            warnings: Vec::new(),
        }
    }

    fn scene_mesh(mesh: xmpr::Mesh, texture_index: Option<usize>) -> SceneMesh {
        SceneMesh {
            mesh,
            texture_index,
            binding: BindConfidence::Unresolved,
            visible: true,
        }
    }

    fn triangle(offset: f32) -> xmpr::Mesh {
        mesh(
            vec![
                [offset, 0.0, 0.0],
                [offset + 1.0, 0.0, 0.0],
                [offset, 1.0, 0.0],
            ],
            vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            vec![[0.0, 0.0, 1.0]; 3],
            vec![[0, 1, 2]],
        )
    }

    #[test]
    fn grid_scales_to_unit_and_world_models() {
        let (unit_extent, unit_step) =
            compute_grid_params(Some(&PreviewBounds::new([-1.0; 3], [1.0; 3])));
        let (world_extent, world_step) =
            compute_grid_params(Some(&PreviewBounds::new([-100.0; 3], [100.0; 3])));
        assert!(unit_extent > 0.0 && unit_step > 0.0);
        assert!(world_extent > unit_extent);
        assert!(world_step > unit_step);
    }

    #[test]
    fn degenerate_bounds_get_a_fallback_grid() {
        let (extent, step) = compute_grid_params(Some(&PreviewBounds::new([0.0; 3], [0.0; 3])));
        assert_eq!((extent, step), (10.0, 1.0));
    }

    #[test]
    fn missing_bounds_get_a_default_grid() {
        assert_eq!(compute_grid_params(None), (50.0, 5.0));
    }

    #[test]
    fn wireframe_indices_expand_each_triangle_into_three_edges() {
        let wire = build_wireframe_indices(&[2, 0, 1, 4, 5, 3]);
        assert_eq!(wire, vec![2, 0, 0, 1, 1, 2, 4, 5, 5, 3, 3, 4]);
    }

    #[test]
    fn wireframe_indices_ignore_a_trailing_partial_triangle() {
        assert_eq!(build_wireframe_indices(&[0, 1, 2, 3, 4]), vec![0, 1, 1, 2, 2, 0]);
    }

    #[test]
    fn concatenation_offsets_each_meshs_indices_by_its_vertex_base() {
        let geometry = build_geometry(&[
            scene_mesh(triangle(0.0), Some(0)),
            scene_mesh(triangle(10.0), Some(1)),
        ]);

        assert_eq!(geometry.vertices.len(), 6);
        assert_eq!(geometry.indices, vec![0, 1, 2, 3, 4, 5]);
        assert_eq!(geometry.parts.len(), 2);
        assert_eq!(
            (geometry.parts[0].index_start, geometry.parts[0].index_count),
            (0, 3)
        );
        assert_eq!(
            (geometry.parts[1].index_start, geometry.parts[1].index_count),
            (3, 3)
        );
        assert_eq!(geometry.parts[0].texture, Some(0));
        assert_eq!(geometry.parts[1].texture, Some(1));
    }

    #[test]
    fn empty_meshes_keep_one_part_per_scene_mesh_so_visibility_stays_aligned() {
        let geometry = build_geometry(&[
            scene_mesh(mesh(Vec::new(), Vec::new(), Vec::new(), Vec::new()), None),
            scene_mesh(triangle(0.0), Some(3)),
            // Positions but no faces: still not drawable.
            scene_mesh(
                mesh(vec![[0.0; 3]; 3], Vec::new(), Vec::new(), Vec::new()),
                None,
            ),
            scene_mesh(triangle(5.0), None),
        ]);

        assert_eq!(geometry.parts.len(), 4);
        assert_eq!(geometry.parts[0].index_count, 0);
        assert_eq!(geometry.parts[1].index_count, 3);
        assert_eq!(geometry.parts[2].index_count, 0);
        assert_eq!(geometry.parts[3].index_count, 3);
        // Skipped meshes contribute no vertices, so the drawable parts stay
        // contiguous in the shared index buffer.
        assert_eq!(geometry.parts[1].index_start, 0);
        assert_eq!(geometry.parts[3].index_start, 3);
        assert_eq!(geometry.vertices.len(), 6);
        assert_eq!(geometry.parts[1].texture, Some(3));
    }

    #[test]
    fn missing_uvs_and_mismatched_normals_get_defaults() {
        let geometry = build_geometry(&[scene_mesh(
            mesh(
                vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                Vec::new(),
                // One normal for three positions: unusable.
                vec![[1.0, 0.0, 0.0]],
                vec![[0, 1, 2]],
            ),
            None,
        )]);

        for vertex in &geometry.vertices {
            assert_eq!(vertex.uv, [0.0, 0.0]);
            assert_eq!(vertex.normal, [0.0, 1.0, 0.0]);
        }
    }

    #[test]
    fn faces_pointing_outside_the_vertex_range_are_dropped() {
        let geometry = build_geometry(&[scene_mesh(
            mesh(
                vec![[0.0; 3], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                Vec::new(),
                Vec::new(),
                vec![[0, 1, 2], [0, 1, 9]],
            ),
            None,
        )]);

        assert_eq!(geometry.indices, vec![0, 1, 2]);
        assert_eq!(geometry.parts[0].index_count, 3);
    }

    #[test]
    fn bounds_and_focus_are_reported_in_display_space() {
        // X is mirrored for display, so an archive sitting at +x is framed at -x.
        let geometry = build_geometry(&[scene_mesh(
            mesh(
                vec![[2.0, 0.0, 0.0], [4.0, 0.0, 0.0], [2.0, 3.0, 6.0]],
                Vec::new(),
                Vec::new(),
                vec![[0, 1, 2]],
            ),
            None,
        )]);

        assert_eq!(geometry.bounds, PreviewBounds::new([-4.0, 0.0, 0.0], [-2.0, 3.0, 6.0]));
        let focus = geometry.focus_target;
        assert!((focus[0] - -8.0 / 3.0).abs() < 1e-5);
        assert!((focus[1] - 1.0).abs() < 1e-5);
        assert!((focus[2] - 2.0).abs() < 1e-5);
    }

    #[test]
    fn geometry_from_no_meshes_is_empty_and_not_nan() {
        let geometry = build_geometry(&[]);
        assert!(geometry.vertices.is_empty());
        assert!(geometry.indices.is_empty());
        assert!(geometry.parts.is_empty());
        assert_eq!(geometry.bounds, PreviewBounds::new([0.0; 3], [0.0; 3]));
        assert_eq!(geometry.focus_target, [0.0; 3]);
    }

    #[test]
    fn a_short_visible_slice_leaves_the_remaining_parts_visible() {
        let visible = [false, true];
        assert!(!part_is_visible(&visible, 0));
        assert!(part_is_visible(&visible, 1));
        assert!(part_is_visible(&visible, 2));
        assert!(part_is_visible(&[], 0));
    }

    #[test]
    fn wireframe_ranges_double_the_triangle_range_and_stay_in_bounds() {
        let part = GpuPart {
            index_start: 3,
            index_count: 6,
            texture: None,
        };
        assert_eq!(wireframe_range(&part, 18), (6, 18));
        // A truncated wireframe buffer clamps instead of overrunning.
        assert_eq!(wireframe_range(&part, 8), (6, 8));
        let empty = GpuPart {
            index_start: 3,
            index_count: 0,
            texture: None,
        };
        let (start, end) = wireframe_range(&empty, 18);
        assert!(start >= end);
    }

    fn transform(m: [[f32; 4]; 4], v: [f32; 4]) -> [f32; 4] {
        let mut out = [0.0f32; 4];
        for row in 0..4 {
            for col in 0..4 {
                out[row] += m[col][row] * v[col];
            }
        }
        out
    }

    #[test]
    fn mat4_mul_with_identity_is_a_no_op() {
        let m = [
            [1.0, 2.0, 3.0, 4.0],
            [5.0, 6.0, 7.0, 8.0],
            [9.0, 10.0, 11.0, 12.0],
            [13.0, 14.0, 15.0, 16.0],
        ];
        assert_eq!(mat4_mul(m, mat4_identity()), m);
        assert_eq!(mat4_mul(mat4_identity(), m), m);
    }

    #[test]
    fn mat4_mul_applies_the_first_argument_first() {
        let mut translate = mat4_identity();
        translate[3] = [1.0, 2.0, 3.0, 1.0];
        let mut scale = mat4_identity();
        scale[0][0] = 2.0;
        scale[1][1] = 2.0;
        scale[2][2] = 2.0;

        // translate then scale => (1,2,3) * 2
        let combined = mat4_mul(translate, scale);
        let out = transform(combined, [0.0, 0.0, 0.0, 1.0]);
        assert!((out[0] - 2.0).abs() < 1e-5);
        assert!((out[1] - 4.0).abs() < 1e-5);
        assert!((out[2] - 6.0).abs() < 1e-5);
    }

    #[test]
    fn perspective_maps_the_near_and_far_planes_to_zero_and_one() {
        let p = perspective(45.0f32.to_radians(), 1.5, 0.5, 100.0);
        let near = transform(p, [0.0, 0.0, -0.5, 1.0]);
        let far = transform(p, [0.0, 0.0, -100.0, 1.0]);
        assert!(near[3] > 0.0 && far[3] > 0.0);
        assert!((near[2] / near[3]).abs() < 1e-4);
        assert!(((far[2] / far[3]) - 1.0).abs() < 1e-4);
    }

    #[test]
    fn look_at_puts_the_eye_at_the_view_space_origin_and_the_target_in_front() {
        let camera = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        let view = look_at(&camera);

        let eye = camera.eye();
        let at_eye = transform(view, [eye[0], eye[1], eye[2], 1.0]);
        assert!(at_eye[0].abs() < 1e-3);
        assert!(at_eye[1].abs() < 1e-3);
        assert!(at_eye[2].abs() < 1e-3);

        let t = camera.target;
        let at_target = transform(view, [t[0], t[1], t[2], 1.0]);
        // The target sits down -Z at the orbit distance.
        assert!(at_target[2] < 0.0);
        assert!((at_target[2] + camera.distance).abs() < 1e-2);
    }

    #[test]
    fn uniforms_mirror_x_and_keep_the_camera_position_in_display_space() {
        let camera = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        let uniforms = build_uniforms(&camera, 800, 600, true);
        assert_eq!(uniforms.model[0][0], -1.0);
        assert_eq!(uniforms.use_texture, 1.0);
        assert_eq!(uniforms.camera_pos, camera.eye());
        assert_eq!(build_uniforms(&camera, 800, 600, false).use_texture, 0.0);
        assert!(uniforms.mvp.iter().flatten().all(|v| v.is_finite()));
    }

    #[test]
    fn uniforms_survive_a_zero_sized_viewport() {
        let camera = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        let uniforms = build_uniforms(&camera, 0, 0, false);
        assert!(uniforms.mvp.iter().flatten().all(|v| v.is_finite()));
    }
}
