# Launch the viewer and capture ITS OWN window content to a PNG, then close it.
# Uses PrintWindow with PW_RENDERFULLCONTENT so an occluding window cannot be
# captured by mistake (CopyFromScreen grabs whatever sits at those coordinates).
param(
    [string]$Exe = "target\release\age_viewer.exe",
    [string]$Out = "ui_capture.png",
    [int]$WaitSeconds = 12
)

Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$proc = Start-Process -FilePath $Exe -PassThru
Start-Sleep -Seconds $WaitSeconds
$proc.Refresh()

$handle = $proc.MainWindowHandle
if ($handle -eq [IntPtr]::Zero) {
    Write-Output "NO_WINDOW"
    $proc.Kill()
    exit 1
}

# SW_RESTORE then foreground; best effort, PrintWindow works either way.
[void][Win]::ShowWindow($handle, 9)
[void][Win]::SetForegroundWindow($handle)
Start-Sleep -Milliseconds 1200

$rect = New-Object Win+RECT
[void][Win]::GetWindowRect($handle, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
Write-Output "WINDOW ${width}x${height} pid=$($proc.Id) title=$($proc.MainWindowTitle)"

$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
# 2 = PW_RENDERFULLCONTENT, required for GPU-composited (wgpu) windows.
$ok = [Win]::PrintWindow($handle, $hdc, 2)
$graphics.ReleaseHdc($hdc)
Write-Output "PRINTWINDOW ok=$ok"

# Report the corner and centre pixels so a blank capture is obvious in the log.
$corner = $bitmap.GetPixel(4, 4)
$centre = $bitmap.GetPixel([int]($width / 2), [int]($height / 2))
Write-Output ("CORNER #{0:X2}{1:X2}{2:X2}" -f $corner.R, $corner.G, $corner.B)
Write-Output ("CENTRE #{0:X2}{1:X2}{2:X2}" -f $centre.R, $centre.G, $centre.B)

$bitmap.Save((Join-Path (Get-Location) $Out), [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()

$proc.Kill()
Write-Output "SAVED $Out"
