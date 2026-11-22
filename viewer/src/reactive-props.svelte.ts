export function reactiveProps<T extends object>(initial: T): T {
  const props = $state(initial)
  return props
}
