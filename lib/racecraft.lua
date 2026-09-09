-- Verve / racecraft.lua  (v0.2)
-- Our own racecraft, built from CSP AI primitives. Per AI car, each frame we read the gap to
-- the nearest car ahead/behind and decide a state:
--   ATTACK  -- a car within striking range and we're keeping up -> tuck in (less caution), raise
--             aggression, and on a straight pull off-line to set up a pass (slipstream + move
--             alongside). Collision-awareness stays ON, so it positions, it doesn't ram.
--   DEFEND  -- a faster car right behind -> make ONE decisive move to cover a side and hold it
--             (no weaving), slightly higher aggression.
--   CRUISE  -- clear track -> return to the racing line, neutral aggression.
-- The line offset is slew-limited so cars glide across, never dart. Everything pcall-guarded.
--
-- evaluate(i, dt) applies spline-offset + aggression itself and RETURNS a caution delta for the
-- app to fold into the single setAICaution call (so it doesn't fight the human layer's caution).

local R = {}
R.ENABLED   = true
R.INTENSITY = 0.7        -- 0..1.5 scales the whole effect
R.attacking = 0
R.defending = 0

local ATTACK_GAP   = 0.008    -- spline-fraction gap to "start pressuring" the car ahead
local PASS_GAP     = 0.0035   -- close enough (on a straight) to pull out for the pass
local DEFEND_GAP   = 0.005    -- car behind this close (and faster) -> defend
local FASTER_MARGIN= 3.0      -- km/h: only attack if we're not slower than this vs the car ahead
local ATTACK_OFFSET= 0.5      -- how far off-line to pull when passing (fraction of half-width)
local DEFEND_OFFSET= 0.4
local CAUTION_ATTACK = -0.6   -- lower caution = close right up
local CAUTION_DEFEND = -0.25
local AGGR_ATTACK  = 0.95
local AGGR_DEFEND  = 0.80
local AGGR_CRUISE  = 0.55
local OFFSET_SLEW  = 1.2      -- units/sec the line offset may move (anti-dart)
local SPEED_MIN    = 30.0     -- below this = launch/slow, no racecraft

local curOffset = {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function hash01(n)
    local x = (n * 2654435761) % 2147483647
    x = (x * 1103515245 + 12345) % 2147483647
    return x / 2147483647
end
local function side(i) return (hash01(i * 5 + 2) < 0.5) and 1 or -1 end   -- stable per-car pass side

function R.evaluate(i, dt)
    if not R.ENABLED then return 0 end
    local caut = 0
    local state = 0    -- 0 cruise, 1 attack, 2 defend
    pcall(function()
        local me = ac.getCar(i)
        if not me or not me.isAIControlled then return end
        local spd = me.speedKmh or 0
        if spd < SPEED_MIN then return end
        if me.isInPitlane then return end
        local mySpline = me.splinePosition
        if mySpline == nil then return end

        -- nearest ahead / behind (by spline gap), with their speeds
        local gapA, aheadSpd, gapB, behindSpd = 1e9, 0, 1e9, 0
        local sim = ac.getSim()
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition then
                    local d = oc.splinePosition - mySpline
                    if d < 0 then d = d + 1 end
                    if d > 0 and d < gapA then gapA = d; aheadSpd = oc.speedKmh or 0 end
                    local b = mySpline - oc.splinePosition
                    if b < 0 then b = b + 1 end
                    if b > 0 and b < gapB then gapB = b; behindSpd = oc.speedKmh or 0 end
                end
            end
        end

        -- straightness (only reposition off-line on straights/fast bits)
        local straight = 1
        local st = me.steer
        if type(st) == "number" then straight = clamp(1 - math.abs(st) / 0.35, 0, 1) end

        local targetOffset = 0
        local aggr = AGGR_CRUISE

        if gapA < ATTACK_GAP and spd >= aheadSpd - FASTER_MARGIN then
            state = 1
            aggr = AGGR_ATTACK
            caut = CAUTION_ATTACK * (1 - gapA / ATTACK_GAP)          -- closer = tuck in more
            if gapA < PASS_GAP and straight > 0.5 then
                targetOffset = ATTACK_OFFSET * side(i) * straight
            end
        elseif gapB < DEFEND_GAP and behindSpd > spd - FASTER_MARGIN then
            state = 2
            aggr = AGGR_DEFEND
            caut = CAUTION_DEFEND
            if straight > 0.5 then targetOffset = DEFEND_OFFSET * side(i) * straight end
        end

        caut = caut * R.INTENSITY
        targetOffset = targetOffset * R.INTENSITY

        -- slew the line offset so the move is smooth, not a dart
        local cur = curOffset[i] or 0
        local step = OFFSET_SLEW * (dt > 0 and dt < 0.5 and dt or 0.016)
        if targetOffset > cur + step then cur = cur + step
        elseif targetOffset < cur - step then cur = cur - step
        else cur = targetOffset end
        curOffset[i] = cur

        physics.setAISplineOffset(i, clamp(cur, -1, 1), false)       -- awareness ON = won't ram
        physics.setAIAggression(i, clamp(aggr, 0, 1))
    end)
    if state == 1 then R.attacking = R.attacking + 1
    elseif state == 2 then R.defending = R.defending + 1 end
    return caut
end

function R.beginFrame() R.attacking = 0; R.defending = 0 end
function R.reset() curOffset = {} end

return R
