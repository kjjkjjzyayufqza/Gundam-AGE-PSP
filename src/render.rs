//! Orbit camera and view state for the 3D preview.
//!
//! Adapted from the gvg_np preview camera: right-handed, Y-up, with the camera
//! orbiting a target point. `frame_bounds` fits an arbitrary model, which matters
//! here because AGE character meshes are unit-scale (normalized s16 positions)
//! while map meshes span hundreds of world units.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PreviewBounds {
    pub min: [f32; 3],
    pub max: [f32; 3],
}

impl PreviewBounds {
    pub fn new(min: [f32; 3], max: [f32; 3]) -> Self {
        Self { min, max }
    }

    pub fn center(&self) -> [f32; 3] {
        [
            (self.min[0] + self.max[0]) * 0.5,
            (self.min[1] + self.max[1]) * 0.5,
            (self.min[2] + self.max[2]) * 0.5,
        ]
    }

    pub fn extent(&self) -> [f32; 3] {
        [
            (self.max[0] - self.min[0]).abs(),
            (self.max[1] - self.min[1]).abs(),
            (self.max[2] - self.min[2]).abs(),
        ]
    }

    pub fn max_dimension(&self) -> f32 {
        self.extent().into_iter().fold(0.0_f32, f32::max)
    }

    pub fn radius(&self) -> f32 {
        let e = self.extent();
        (e[0] * e[0] + e[1] * e[1] + e[2] * e[2]).sqrt() * 0.5
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PreviewCamera {
    pub target: [f32; 3],
    pub yaw: f32,
    pub pitch: f32,
    pub distance: f32,
    pub fov_y_radians: f32,
    pub near: f32,
    pub far: f32,
}

impl PreviewCamera {
    /// Fit the camera to bounds, looking slightly down at the model front.
    pub fn frame_bounds(bounds: PreviewBounds) -> Self {
        Self::frame_bounds_with_target(bounds, bounds.center())
    }

    pub fn frame_bounds_with_target(bounds: PreviewBounds, target: [f32; 3]) -> Self {
        let radius = bounds.radius().max(f32::MIN_POSITIVE);
        let fov_y_radians = 45.0_f32.to_radians();
        // Scale near/far to the model so unit-scale characters and 200-unit maps
        // both get usable depth precision.
        let fit_distance = radius / (fov_y_radians * 0.5).tan();
        let distance = (fit_distance * 1.25).max(radius * 0.05).max(1e-3);
        Self {
            target,
            yaw: std::f32::consts::PI + 0.35,
            pitch: -0.28,
            distance,
            fov_y_radians,
            near: (distance * 0.001).max(1e-4),
            far: (distance * 20.0).max(10.0),
        }
    }

    pub fn orbit(&mut self, delta_yaw: f32, delta_pitch: f32) {
        self.yaw += delta_yaw;
        self.pitch = (self.pitch + delta_pitch).clamp(-1.45, 1.45);
    }

    /// Multiplicative zoom; `delta` is a fraction of the current distance.
    pub fn zoom(&mut self, delta: f32) {
        self.distance = (self.distance * (1.0 + delta)).max(1e-4);
        self.near = (self.distance * 0.001).max(1e-5);
        self.far = (self.distance * 20.0).max(10.0);
    }

    /// Pan the target across the view plane, scaled so it feels constant on screen.
    pub fn pan(&mut self, delta_x: f32, delta_y: f32) {
        let (right, up) = self.right_up();
        let scale = self.distance * 0.002;
        for axis in 0..3 {
            self.target[axis] += right[axis] * delta_x * scale + up[axis] * delta_y * scale;
        }
    }

    pub fn eye(&self) -> [f32; 3] {
        let forward = self.forward();
        [
            self.target[0] - forward[0] * self.distance,
            self.target[1] - forward[1] * self.distance,
            self.target[2] - forward[2] * self.distance,
        ]
    }

    pub fn forward(&self) -> [f32; 3] {
        let cos_pitch = self.pitch.cos();
        normalize([
            self.yaw.sin() * cos_pitch,
            self.pitch.sin(),
            self.yaw.cos() * cos_pitch,
        ])
    }

    fn right_up(&self) -> ([f32; 3], [f32; 3]) {
        let forward = self.forward();
        let right = normalize(cross([0.0, 1.0, 0.0], forward));
        let up = cross(forward, right);
        (right, up)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct PreviewState {
    pub camera: Option<PreviewCamera>,
    pub show_wireframe: bool,
    pub show_grid: bool,
    pub show_axes: bool,
    pub show_textures: bool,
}

impl Default for PreviewState {
    fn default() -> Self {
        Self {
            camera: None,
            show_wireframe: false,
            show_grid: true,
            show_axes: true,
            show_textures: true,
        }
    }
}

fn cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn normalize(v: [f32; 3]) -> [f32; 3] {
    let len = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
    if len <= f32::EPSILON {
        [0.0, 0.0, 1.0]
    } else {
        [v[0] / len, v[1] / len, v[2] / len]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unit_scale_and_world_scale_bounds_both_get_sane_distance() {
        let unit = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        let world = PreviewCamera::frame_bounds(PreviewBounds::new([-100.0; 3], [100.0; 3]));
        assert!(unit.distance > 0.0 && unit.distance < 100.0);
        assert!(world.distance > unit.distance);
        assert!(unit.near > 0.0 && unit.near < unit.far);
        assert!(world.near > 0.0 && world.near < world.far);
    }

    #[test]
    fn degenerate_bounds_do_not_produce_nan() {
        let camera = PreviewCamera::frame_bounds(PreviewBounds::new([0.0; 3], [0.0; 3]));
        assert!(camera.distance.is_finite());
        assert!(camera.distance > 0.0);
        assert!(camera.near.is_finite() && camera.far.is_finite());
    }

    #[test]
    fn pitch_is_clamped_away_from_the_poles() {
        let mut camera = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        camera.orbit(0.0, 10.0);
        assert!(camera.pitch <= 1.45);
        camera.orbit(0.0, -100.0);
        assert!(camera.pitch >= -1.45);
    }

    #[test]
    fn zoom_never_reaches_zero_distance() {
        let mut camera = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        for _ in 0..200 {
            camera.zoom(-0.9);
        }
        assert!(camera.distance > 0.0);
    }

    #[test]
    fn eye_sits_behind_the_target_along_forward() {
        let camera = PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3]));
        let eye = camera.eye();
        let forward = camera.forward();
        // target = eye + forward * distance
        for axis in 0..3 {
            let reconstructed = eye[axis] + forward[axis] * camera.distance;
            assert!((reconstructed - camera.target[axis]).abs() < 1e-3);
        }
    }
}
