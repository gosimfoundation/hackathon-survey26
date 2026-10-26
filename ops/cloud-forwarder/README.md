# Cloud forwarder

The backend moved from the Supabase cloud project `vdiemcofukuxglqsmlyz` to the self-hosted
instance at `https://survey26-api.liyao.space` (2026-10-26). CLIs before 1.9.2, contestants'
agents and the Sophon solver still call the cloud function URLs, so the cloud project serves
`index.ts` under the names `survey26-cli`, `kimi-relay` and `sophon`: each request is passed
through unchanged to the same function on the self-hosted backend.

Deploy: run the **Deploy cloud forwarders** workflow (uses the `SUPABASE_ACCESS_TOKEN` and
`SUPABASE_PROJECT_REF` repository secrets). To undo, redeploy the original functions from
`supabase/functions/` (and `function/` in gosimfoundation/survey26-sophon-mail).
