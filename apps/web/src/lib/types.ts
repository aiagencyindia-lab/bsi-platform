import type { components } from "./schema";

type S = components["schemas"];
export type Brand = S["BrandOut"];
export type Metrics = S["MetricsOut"];
export type Deltas = S["DeltasOut"];
export type Sov = S["SovOut"];
export type PromptMetrics = S["PromptMetricsOut"];
export type Observation = S["ObservationOut"];
export type ObservationDetail = S["ObservationDetail"];
