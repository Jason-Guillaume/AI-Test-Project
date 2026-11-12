// 单模型工作台播放器：音频元素始终挂载在工作区中，抽屉开关不会重置播放位置。
import { Alert, Button, Select, Slider, Space, Typography } from 'antd';
import {
  InfoCircleOutlined, PauseOutlined, PlayCircleOutlined, SettingOutlined,
  StepBackwardOutlined, StepForwardOutlined,
} from '@ant-design/icons';
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from 'react';
import type { JsonValue } from '../contracts';
import { observeAudioSource, rememberAudioPlayback } from './audioPlaybackMemory.mjs';

const { Text } = Typography;

interface AudioWorkbenchPlayerProps {
  src: string | null;
  durationSeconds: number | null;
  audioRef: RefObject<HTMLAudioElement>;
  peaks: JsonValue;
  onAudioInfo: () => void;
  onRequestParameters: () => void;
  onTimeChange: (seconds: number) => void;
  onClearPlaybackRange: () => void;
}

/** 用媒体元素实际报告的时长、位置与音量绘制播放器状态。 */
function clockLabel(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—:—';
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  if (minutes >= 60) {
    return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}:${(whole % 60).toString().padStart(2, '0')}`;
  }
  return `${minutes.toString().padStart(2, '0')}:${(whole % 60).toString().padStart(2, '0')}`;
}

function mediaErrorMessage(audio: HTMLAudioElement): string {
  switch (audio.error?.code) {
    case 2: return '音频传输失败。请检查网络或项目出站访问权限后重试。';
    case 3: return '浏览器无法解码此音频。识别文本仍可查看，也可尝试下载源文件后收听。';
    case 4: return '音频来源不可用或格式不受浏览器支持。识别文本仍可查看。';
    default: return '音频播放失败。请检查来源或浏览器支持情况后重试。';
  }
}

/** 仅将后台生成的真实极值压缩为可视条，不在浏览器解码整条音频。 */
function peakBars(peaks: JsonValue): number[] {
  if (!Array.isArray(peaks)) return [];
  const channelArrays = peaks.filter(Array.isArray) as JsonValue[][];
  if (!channelArrays.length) return [];
  const binCount = Math.max(...channelArrays.map((channel) => channel.length));
  if (!binCount) return [];
  const barCount = Math.min(420, binCount);
  return Array.from({ length: barCount }, (_, bar) => {
    const start = Math.floor(bar * binCount / barCount);
    const end = Math.max(start + 1, Math.floor((bar + 1) * binCount / barCount));
    let maximum = 0;
    for (const channel of channelArrays) {
      for (let index = start; index < Math.min(end, channel.length); index += 1) {
        const pair = channel[index];
        if (Array.isArray(pair)) {
          for (const value of pair) {
            if (typeof value === 'number' && Number.isFinite(value)) maximum = Math.max(maximum, Math.abs(value));
          }
        }
      }
    }
    return Math.min(1, maximum);
  });
}

/** 单一 AudioElement 驱动进度、波形定位、音频信息与请求参数入口。 */
export function AudioWorkbenchPlayer({
  src, durationSeconds, audioRef, peaks, onAudioInfo, onRequestParameters, onTimeChange, onClearPlaybackRange,
}: AudioWorkbenchPlayerProps) {
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationSeconds ?? 0);
  const [paused, setPaused] = useState(true);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [volume, setVolume] = useState(1);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const previousSrc = useRef(src);
  const bars = peakBars(peaks);

  // Run routes can replace the workbench component while switching models.
  // Restore the real media position if that happened, and resume only when the
  // previous element was actively playing. A different audio source clears the
  // in-memory snapshot so its old position can never leak into new audio.
  useLayoutEffect(() => {
    const audio = audioRef.current;
    const snapshot = observeAudioSource(src);
    if (snapshot && audio) {
      setCurrentTime(snapshot.currentTime);
      setPaused(snapshot.paused);
      setVolume(snapshot.volume);
      setPlaybackRate(snapshot.playbackRate);
      const shouldRestore = snapshot.currentTime > 0 || !snapshot.paused
        || snapshot.volume !== 1 || snapshot.playbackRate !== 1;
      let cancelled = false;
      const restore = () => {
        if (cancelled || !audio || audio.readyState < 1) return;
        const restoredTime = Number.isFinite(audio.duration)
          ? Math.min(snapshot.currentTime, audio.duration)
          : snapshot.currentTime;
        audio.currentTime = Math.max(0, restoredTime);
        audio.volume = snapshot.volume;
        audio.playbackRate = snapshot.playbackRate;
        setCurrentTime(audio.currentTime);
        onTimeChange(audio.currentTime);
        if (!snapshot.paused) {
          void audio.play().catch(() => {
            setPaused(true);
            setErrorMessage('切换模型后浏览器暂停了回听；点击播放可从当前位置继续。');
            rememberAudioPlayback({ ...snapshot, currentTime: audio.currentTime, paused: true });
          });
        }
      };
      if (shouldRestore) {
        if (audio.readyState >= 1) restore();
        else {
          audio.addEventListener('loadedmetadata', restore, { once: true });
          audio.load();
        }
      }
      return () => {
        cancelled = true;
        audio.removeEventListener('loadedmetadata', restore);
        rememberAudioPlayback({
          source: src ?? '', currentTime: audio.currentTime, paused: audio.paused,
          volume: audio.volume, playbackRate: audio.playbackRate,
        });
      };
    }
    return () => {
      if (audio && src) {
        rememberAudioPlayback({
          source: src, currentTime: audio.currentTime, paused: audio.paused,
          volume: audio.volume, playbackRate: audio.playbackRate,
        });
      }
    };
  }, [src, audioRef, onTimeChange]);

  useEffect(() => {
    setErrorMessage(null);
    setLoading(false);
    if (previousSrc.current !== src) {
      previousSrc.current = src;
      const audio = audioRef.current;
      audio?.pause();
      if (audio && Number.isFinite(audio.duration)) audio.currentTime = 0;
      setCurrentTime(0);
      setDuration(durationSeconds ?? 0);
      setPaused(true);
      onClearPlaybackRange();
    }
  }, [src, durationSeconds, audioRef, onClearPlaybackRange]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;
    /** 同步真实媒体状态，页面及抽屉只读这些值。 */
    const update = () => {
      const position = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
      setCurrentTime(position);
      if (Number.isFinite(audio.duration)) setDuration(audio.duration);
      setPaused(audio.paused);
      setPlaybackRate(audio.playbackRate);
      setVolume(audio.volume);
      onTimeChange(position);
    };
    audio.addEventListener('timeupdate', update);
    audio.addEventListener('durationchange', update);
    audio.addEventListener('play', update);
    audio.addEventListener('pause', update);
    audio.addEventListener('ratechange', update);
    audio.addEventListener('volumechange', update);
    audio.addEventListener('loadedmetadata', update);
    update();
    return () => {
      audio.removeEventListener('timeupdate', update);
      audio.removeEventListener('durationchange', update);
      audio.removeEventListener('play', update);
      audio.removeEventListener('pause', update);
      audio.removeEventListener('ratechange', update);
      audio.removeEventListener('volumechange', update);
      audio.removeEventListener('loadedmetadata', update);
    };
  }, [audioRef, onTimeChange, src]);

  /** 跳到控件给出的时间；只对已报告时长取边界。 */
  const seek = (value: number) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(value)) return;
    onClearPlaybackRange();
    audio.currentTime = Math.max(0, duration > 0 ? Math.min(duration, value) : value);
    setCurrentTime(audio.currentTime);
    onTimeChange(audio.currentTime);
  };

  /** 波形数据只作定位表面；没有服务端峰值时保留播放器的其余控制。 */
  const seekWaveform = (event: MouseEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width > 0 && duration > 0) seek(((event.clientX - bounds.left) / bounds.width) * duration);
  };

  return (
    <div className="asr-player-shell">
      <audio
        ref={audioRef}
        src={src ?? undefined}
        preload="none"
        onLoadStart={() => { setLoading(true); setErrorMessage(null); }}
        onWaiting={() => setLoading(true)}
        onCanPlay={() => { setLoading(false); setErrorMessage(null); }}
        onPlaying={() => { setPaused(false); setLoading(false); setErrorMessage(null); }}
        onPause={() => setPaused(true)}
        onError={(event) => {
          setPaused(true);
          setLoading(false);
          setErrorMessage(mediaErrorMessage(event.currentTarget));
        }}
      />
      {loading && src && <Typography.Text type="secondary">正在加载音频…</Typography.Text>}
      {errorMessage && <Alert
        type="error"
        showIcon
        message={errorMessage}
        action={<Button size="small" onClick={() => {
          const audio = audioRef.current;
          if (!audio) return;
          setErrorMessage(null);
          setLoading(true);
          audio.load();
          void audio.play().catch(() => {
            setLoading(false);
            setErrorMessage('重试仍未能播放。请检查音频来源或浏览器支持情况。');
          });
        }}>重试播放</Button>}
      />}
      <Space className="asr-player-controls" wrap align="center">
        <Button
          type="primary"
          shape="circle"
          icon={paused ? <PlayCircleOutlined /> : <PauseOutlined />}
          aria-label={paused ? '播放音频' : '暂停音频'}
          disabled={!src}
          onClick={() => {
            const audio = audioRef.current;
            if (!audio) return;
            if (audio.paused) {
              onClearPlaybackRange();
              void audio.play().catch(() => {
                setPaused(true);
                setErrorMessage('浏览器拒绝播放或音频暂不可用。请检查来源后重试。');
              });
            } else audio.pause();
          }}
        />
        <Button
          icon={<StepBackwardOutlined />}
          aria-label="后退 5 秒"
          title="后退 5 秒"
          disabled={!src}
          onClick={() => seek(currentTime - 5)}
        >5 秒</Button>
        <Button
          icon={<StepForwardOutlined />}
          aria-label="快进 5 秒"
          title="快进 5 秒"
          disabled={!src}
          onClick={() => seek(currentTime + 5)}
        >5 秒</Button>
        <Text className="asr-player-time">{clockLabel(currentTime)} / {clockLabel(duration || durationSeconds || 0)}</Text>
        <Slider
          className="asr-player-progress"
          min={0}
          max={Math.max(1, duration || durationSeconds || 1)}
          value={Math.min(currentTime, duration || durationSeconds || currentTime)}
          tooltip={{ formatter: (value) => clockLabel(value ?? 0) }}
          onChange={seek}
        />
        <Space className="asr-player-options" size="small" align="center" wrap>
          <Text type="secondary">音量</Text>
          <Slider
            className="asr-player-volume"
            min={0}
            max={1}
            step={0.01}
            value={volume}
            tooltip={{ formatter: (value) => `${Math.round((value ?? 0) * 100)}%` }}
            onChange={(value) => { if (audioRef.current) audioRef.current.volume = value; }}
          />
          <Select
            aria-label="播放倍速"
            size="small"
            value={playbackRate}
            style={{ width: 90 }}
            options={[0.75, 1, 1.25, 1.5, 2].map((value) => ({ value, label: `${value}×` }))}
            onChange={(value) => { if (audioRef.current) audioRef.current.playbackRate = value; }}
          />
          <Button icon={<InfoCircleOutlined />} onClick={onAudioInfo}>音频信息</Button>
          <Button icon={<SettingOutlined />} onClick={onRequestParameters}>请求参数</Button>
        </Space>
      </Space>
      <div
        className={`asr-waveform ${bars.length ? '' : 'is-empty'}`}
        role={bars.length ? 'slider' : undefined}
        aria-label={bars.length ? '音频波形，点击跳转' : '波形尚未生成'}
        aria-valuemin={0}
        aria-valuemax={Math.floor(duration)}
        aria-valuenow={Math.floor(currentTime)}
        tabIndex={bars.length ? 0 : -1}
        onClick={seekWaveform}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') seek(currentTime - 1);
          if (event.key === 'ArrowRight') seek(currentTime + 1);
        }}
      >
        {bars.length ? bars.map((peak, index) => (
          <span key={index} className={duration > 0 && index / bars.length <= currentTime / duration ? 'is-played' : ''}
            style={{ height: `${Math.round(peak * 100)}%` }} />
        )) : <Text type="secondary">服务端波形尚未分析；可在“音频信息”中启动后台分析</Text>}
      </div>
      <div className="asr-player-range">
        <Text type="secondary">当前播放位置由音频播放器报告</Text>
        <Text type="secondary">{clockLabel(currentTime)}</Text>
      </div>
    </div>
  );
}
