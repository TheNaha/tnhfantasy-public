/**
 * Sampler and scheduler vocabularies, exactly as the ComfyUI build in use
 * defines them.
 *
 * These are the two dropdowns behind every sampler/scheduler field in the app
 * (`SamplingSettings`, `BatchGenerate`), and they used to hold 6 of ComfyUI's 47
 * samplers and 4 of its 9 schedulers. `simple`, `ddim_uniform`, `beta`,
 * `linear_quadratic` and `kl_optimal` were unreachable from the UI, which is why
 * "can you add simple" was the question: the value was never missing from
 * ComfyUI, only from here.
 *
 * Provenance — read out of the LIVE ComfyUI instance, not from memory or a
 * docs page. Captured 2026-10-15 from
 *
 *   curl http://100.150.0.26:8188/object_info/KSampler
 *
 * which is the `colab-one` provider (`config.base_model`/`base_url` in the
 * `providers` table). `KSampler.sampler_name` and `KSampler.scheduler` are the
 * authoritative strings the KSampler accepts, so anything absent here cannot be
 * submitted to that ComfyUI at all.
 *
 * Order is ComfyUI's own. It is left alone rather than sorted alphabetically, so
 * the picker reads the same as the node in ComfyUI itself — a user comparing the
 * two finds the entry in the same place. Sorting 47 entries for legibility would
 * be a nicer-looking list and a worse-matching one.
 *
 * Do NOT trim this list because an entry is unfamiliar. Every value here is one
 * the installed ComfyUI accepts, and the only cost of carrying one the user never
 * picks is one more line in a dropdown. The value of the list being complete is
 * that a workflow pasted in from elsewhere, or reused from an old image, already
 * has an option to land on — see `withCurrentOption` in
 * `src/constants/options.js`, which covers a value this file does not know.
 */

// KSampler.sampler_name — 47 entries.
export const SAMPLERS = [
    'euler',
    'euler_cfg_pp',
    'euler_ancestral',
    'euler_ancestral_cfg_pp',
    'heun',
    'heunpp2',
    'exp_heun_2_x0',
    'exp_heun_2_x0_sde',
    'dpm_2',
    'dpm_2_ancestral',
    'lms',
    'dpm_fast',
    'dpm_adaptive',
    'dpmpp_2s_ancestral',
    'dpmpp_2s_ancestral_cfg_pp',
    'dpmpp_sde',
    'dpmpp_sde_gpu',
    'dpmpp_2m',
    'dpmpp_2m_cfg_pp',
    'dpmpp_2m_sde',
    'dpmpp_2m_sde_gpu',
    'dpmpp_2m_sde_heun',
    'dpmpp_2m_sde_heun_gpu',
    'dpmpp_3m_sde',
    'dpmpp_3m_sde_gpu',
    'ddpm',
    'lcm',
    'ipndm',
    'ipndm_v',
    'deis',
    'cfgpp_ud10_ab',
    'res_multistep',
    'res_multistep_cfg_pp',
    'res_multistep_ancestral',
    'res_multistep_ancestral_cfg_pp',
    'gradient_estimation',
    'gradient_estimation_cfg_pp',
    'er_sde',
    'seeds_2',
    'seeds_3',
    'sa_solver',
    'sa_solver_pece',
    'ddim',
    'uni_pc',
    'uni_pc_bh2',
];

// KSampler.scheduler — 9 entries. `simple` is one of them.
export const SCHEDULERS = [
    'simple',
    'sgm_uniform',
    'karras',
    'exponential',
    'ddim_uniform',
    'beta',
    'normal',
    'linear_quadratic',
    'kl_optimal',
];
