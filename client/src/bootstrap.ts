// Explicit preview avoids replacing the team's working v1 client with half a v2.
if (new URLSearchParams(location.search).has('scenario-preview')) {
  await import('./scenarios/preview');
} else {
  await import('./main');
}
export {};
