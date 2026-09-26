-- Verve / update.lua
-- Non-intrusive update check: fetch a tiny version.json, compare to this build, and expose a
-- banner for the UI. NOTIFY + LINK ONLY -- never downloads, never writes to disk (a bad
-- self-update can brick an app mid-session, and users distrust mods that write on their own).

local U = {}
U.LOCAL_VERSION = "0.14.4"
-- Raw version.json in the GitHub repo (updated on every release by release.sh).
U.VERSION_URL   = "https://raw.githubusercontent.com/ververacing/verve/main/version.json"

U.latest, U.downloadUrl, U.summary = nil, nil, nil
-- the link comes from a file fetched over the network: only ever open the project's own GitHub
function U.safeUrl(u) return type(u) == 'string' and u:sub(1, 36) == 'https://github.com/ververacing/verve' end
local checked = false

local function nums(v)
    local t = {}
    for n in tostring(v):gmatch("%d+") do t[#t + 1] = tonumber(n) end
    return t
end
local function newer(a, b)                 -- is version a newer than b?
    local pa, pb = nums(a), nums(b)
    for i = 1, math.max(#pa, #pb) do
        local x, y = pa[i] or 0, pb[i] or 0
        if x ~= y then return x > y end
    end
    return false
end

function U.check()
    if checked then return end
    checked = true
    pcall(function()
        web.get(U.VERSION_URL, function(err, res)
            if err or not res or res.status ~= 200 or not res.body then return end
            local ver = res.body:match('"version"%s*:%s*"([^"]+)"')
            local url = res.body:match('"url"%s*:%s*"([^"]+)"')
            local sum = res.body:match('"summary"%s*:%s*"([^"]+)"')
            if ver and newer(ver, U.LOCAL_VERSION) then
                U.latest, U.downloadUrl, U.summary = ver, U.safeUrl(url) and url or nil, sum
            end
        end)
    end)
end

return U
