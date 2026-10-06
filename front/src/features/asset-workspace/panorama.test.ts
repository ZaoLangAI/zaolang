import { describe, expect, it } from 'vitest';

import { fovDistance, panoramaPose } from './panorama';

describe('panoramaPose', () => {
  it('reads yaw as the azimuth, wrapping and snapping to 45°', () => {
    expect(panoramaPose({ yaw: 0, pitch: 0, fov: 60 })).toEqual({
      azimuth: 0,
      elevation: 0,
      distance: 'medium',
    });
    expect(panoramaPose({ yaw: 178, pitch: 0, fov: 60 }).azimuth).toBe(180);
    expect(panoramaPose({ yaw: -90, pitch: 0, fov: 60 }).azimuth).toBe(270);
    expect(panoramaPose({ yaw: 100, pitch: 0, fov: 60 }).azimuth).toBe(90);
    expect(panoramaPose({ yaw: 350, pitch: 0, fov: 60 }).azimuth).toBe(0);
    expect(panoramaPose({ yaw: -200, pitch: 0, fov: 60 }).azimuth).toBe(180);
  });

  it('turns looking down into a high camera and looking up into a low one', () => {
    expect(panoramaPose({ yaw: 0, pitch: -55, fov: 60 }).elevation).toBe(60);
    expect(panoramaPose({ yaw: 0, pitch: -20, fov: 60 }).elevation).toBe(30);
    expect(panoramaPose({ yaw: 0, pitch: 8, fov: 60 }).elevation).toBe(0);
    expect(panoramaPose({ yaw: 0, pitch: 40, fov: 60 }).elevation).toBe(-30);
    expect(panoramaPose({ yaw: 0, pitch: 85, fov: 60 }).elevation).toBe(-30);
  });

  it('maps the field of view to a distance', () => {
    expect(fovDistance(25)).toBe('close');
    expect(fovDistance(40)).toBe('close');
    expect(fovDistance(41)).toBe('medium');
    expect(fovDistance(79)).toBe('medium');
    expect(fovDistance(80)).toBe('wide');
    expect(fovDistance(110)).toBe('wide');
    expect(panoramaPose({ yaw: 180, pitch: -50, fov: 100 })).toEqual({
      azimuth: 180,
      elevation: 60,
      distance: 'wide',
    });
  });
});
