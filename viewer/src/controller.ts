export type ControllerAction = 'previous' | 'next' | 'back'

export interface ControllerInput {
  handedness: string
  gamepad?: { axes: readonly number[]; buttons: readonly { pressed: boolean }[] } | null
}

export const THUMBSTICK_X_AXIS = 2
export const BACK_BUTTON = 5
export const STICK_PRESS_THRESHOLD = 0.7
export const STICK_RELEASE_THRESHOLD = 0.3

interface HeldState {
  stick: boolean
  back: boolean
}

export function createControllerReader(): (inputs: Iterable<ControllerInput>) => ControllerAction[] {
  const held = new Map<string, HeldState>()
  return (inputs) => {
    const actions: ControllerAction[] = []
    for (const { handedness, gamepad } of inputs) {
      if (!gamepad) continue
      const state = held.get(handedness) ?? { stick: false, back: false }
      const x = gamepad.axes[THUMBSTICK_X_AXIS] ?? 0
      if (!state.stick && Math.abs(x) >= STICK_PRESS_THRESHOLD) {
        actions.push(x > 0 ? 'next' : 'previous')
        state.stick = true
      } else if (state.stick && Math.abs(x) < STICK_RELEASE_THRESHOLD) {
        state.stick = false
      }
      const back = gamepad.buttons[BACK_BUTTON]?.pressed ?? false
      if (back && !state.back) actions.push('back')
      state.back = back
      held.set(handedness, state)
    }
    return actions
  }
}
