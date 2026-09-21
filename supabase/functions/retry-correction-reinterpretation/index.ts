import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "npm:@supabase/server@^1";

const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default {
  fetch: withSupabase({auth:"user"}, async (req,ctx)=>{
    if(req.method!=="POST") return Response.json({error:"method_not_allowed"},{status:405});
    let body:{correction_id?:string};
    try{body=await req.json()}catch{return Response.json({error:"invalid_json"},{status:400})}

    const correctionId=
      typeof body.correction_id==="string"&&UUID_RE.test(body.correction_id)
        ? body.correction_id : null;
    if(!correctionId) return Response.json({error:"invalid_correction_id"},{status:400});

    const {data:correction,error}=await ctx.supabase
      .from("corrections")
      .select("id,job_id,user_id,exception_id,input_kind,confirmation_status,proposed_patch")
      .eq("id",correctionId).maybeSingle();
    if(error) return Response.json({error:"correction_lookup_failed"},{status:502});
    if(!correction) return Response.json({error:"correction_not_found"},{status:404});
    if(correction.confirmation_status!=="pending"||correction.proposed_patch){
      return Response.json({error:"correction_not_reinterpretable"},{status:409});
    }

    const {data:exception,error:exError}=await ctx.supabase
      .from("exceptions")
      .select("id,status")
      .eq("id",correction.exception_id)
      .eq("job_id",correction.job_id)
      .maybeSingle();
    if(exError) return Response.json({error:"exception_lookup_failed"},{status:502});
    if(!exception||exception.status!=="awaiting_reinterpretation"){
      return Response.json({error:"exception_not_awaiting_reinterpretation"},{status:409});
    }

    const token=Deno.env.get("GITHUB_TOKEN");
    const repository=Deno.env.get("GITHUB_REPOSITORY")??"PBHSVVI/PBHS_MEMO_CONVERTER";
    const ref=Deno.env.get("GITHUB_REF")??"main";
    if(!token) return Response.json({error:"server_not_configured"},{status:500});

    const response=await fetch(
      `https://api.github.com/repos/${repository}/actions/workflows/reinterpret-correction.yml/dispatches`,
      {
        method:"POST",
        headers:{
          Authorization:`Bearer ${token}`,
          Accept:"application/vnd.github+json",
          "X-GitHub-Api-Version":"2022-11-28",
          "Content-Type":"application/json",
          "User-Agent":"PBHS-Memo-Converter-Phase7",
        },
        body:JSON.stringify({ref,inputs:{correction_id:correctionId}}),
      }
    );

    if(!response.ok){
      return Response.json(
        {error:"github_dispatch_failed",http_status:response.status},
        {status:502}
      );
    }

    await ctx.supabaseAdmin.from("job_events").insert({
      job_id:correction.job_id,
      user_id:correction.user_id,
      event_type:"phase7_correction_reinterpretation_redispatched",
      stage:"phase7_awaiting_reinterpretation",
      payload:{correction_id:correctionId,repository,ref},
    });

    return Response.json(
      {ok:true,correction_id:correctionId,status:"dispatched"},
      {status:202}
    );
  }),
};