import { describe, expect, it } from 'vitest'
import { createControllerReader, type ControllerInput } from './controller'

function controller(handedness: string, { x = 0, back = false } = {}): ControllerInput {
  const buttons = Array.from({ length: 7 }, (_, i) => ({ pressed: i === 5 && back }))
  return { handedness, gamepad: { axes: [0, 0, x, 0], buttons } }
}

describe('createControllerReader', () => {
  it('goes to the next photo when the thumbstick is pushed right', () => {
    const read = createControllerReader()

    expect(read([controller('right', { x: 0.9 })])).toEqual(['next'])
  })

  it('goes to the previous photo when the thumbstick is pushed left', () => {
    const read = createControllerReader()

    expect(read([controller('left', { x: -0.9 })])).toEqual(['previous'])
  })

  it('ignores a thumbstick tilted less than the press threshold', () => {
    const read = createControllerReader()

    expect(read([controller('right', { x: 0.6 })])).toEqual([])
  })

  it('moves only once while the thumbstick is held', () => {
    const read = createControllerReader()

    read([controller('right', { x: 0.9 })])

    expect(read([controller('right', { x: 1 })])).toEqual([])
    expect(read([controller('right', { x: 0.5 })])).toEqual([])
  })

  it('moves again after the thumbstick returns near the center', () => {
    const read = createControllerReader()
    read([controller('right', { x: 0.9 })])

    read([controller('right', { x: 0.2 })])

    expect(read([controller('right', { x: 0.9 })])).toEqual(['next'])
  })

  it('goes back to the list once per press of B or Y', () => {
    const read = createControllerReader()

    expect(read([controller('right', { back: true })])).toEqual(['back'])
    expect(read([controller('right', { back: true })])).toEqual([])
    read([controller('right')])
    expect(read([controller('right', { back: true })])).toEqual(['back'])
    expect(read([controller('left', { back: true })])).toEqual(['back'])
  })

  it('reads each controller on its own', () => {
    const read = createControllerReader()
    read([controller('left', { x: -0.9 }), controller('right')])

    expect(read([controller('left', { x: -0.9 }), controller('right', { x: 0.9 })])).toEqual(['next'])
  })

  it('ignores input sources without a gamepad', () => {
    const read = createControllerReader()

    expect(read([{ handedness: 'none' }, { handedness: 'left', gamepad: null }])).toEqual([])
  })

  it('ignores a gamepad without a thumbstick or B/Y button', () => {
    const read = createControllerReader()

    expect(read([{ handedness: 'right', gamepad: { axes: [], buttons: [] } }])).toEqual([])
  })
})
