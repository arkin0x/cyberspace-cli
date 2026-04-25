"""Tests for cyberspace_cli.cloud_orchestration module."""
import pytest
from unittest.mock import AsyncMock, patch
from cyberspace_cli.cloud_orchestration import (
    CloudComputeResult,
    select_axis_for_cloud,
    compute_axis_in_cloud,
    compute_spatial_roots_hybrid,
)


class TestSelectAxisForCloud:
    """Test axis selection logic."""
    
    def test_all_axes_within_local_capacity(self):
        """No cloud needed when all heights are within limit."""
        result = select_axis_for_cloud(5, 6, 7, max_compute_height=16)
        assert result is None
    
    def test_x_axis_highest(self):
        """X axis selected when it has highest LCA height."""
        result = select_axis_for_cloud(20, 15, 10, max_compute_height=16)
        assert result == 'x'
    
    def test_y_axis_highest(self):
        """Y axis selected when it has highest LCA height."""
        result = select_axis_for_cloud(10, 25, 15, max_compute_height=16)
        assert result == 'y'
    
    def test_z_axis_highest(self):
        """Z axis selected when it has highest LCA height."""
        result = select_axis_for_cloud(10, 15, 30, max_compute_height=16)
        assert result == 'z'
    
    def test_tie_priority_x_over_y(self):
        """X wins tie over Y."""
        result = select_axis_for_cloud(20, 20, 10, max_compute_height=16)
        assert result == 'x'
    
    def test_tie_priority_x_over_z(self):
        """X wins tie over Z."""
        result = select_axis_for_cloud(20, 10, 20, max_compute_height=16)
        assert result == 'x'
    
    def test_tie_priority_y_over_z(self):
        """Y wins tie over Z when X is lower."""
        result = select_axis_for_cloud(10, 20, 20, max_compute_height=16)
        assert result == 'y'
    
    def test_exactly_at_limit(self):
        """No cloud needed when height equals limit."""
        result = select_axis_for_cloud(16, 15, 14, max_compute_height=16)
        assert result is None


class TestCloudComputeResult:
    """Test CloudComputeResult dataclass."""
    
    def test_basic_creation(self):
        """Create result with required fields."""
        result = CloudComputeResult(
            axis='x',
            axis_root=12345,
            lca_height=20,
            base=1000000,
        )
        assert result.axis == 'x'
        assert result.axis_root == 12345
        assert result.lca_height == 20
        assert result.base == 1000000
        assert result.job_id is None
        assert result.cost_sats == 0
    
    def test_full_creation(self):
        """Create result with all fields."""
        result = CloudComputeResult(
            axis='y',
            axis_root=67890,
            lca_height=25,
            base=2000000,
            job_id="test-job-123",
            cost_sats=5,
        )
        assert result.job_id == "test-job-123"
        assert result.cost_sats == 5


class TestComputeAxisInCloud:
    """Test cloud compute for single axis."""
    
    @pytest.mark.asyncio
    async def test_compute_x_axis(self):
        """Compute X axis in cloud."""
        mock_result = {
            "axis_root_hex": "0xabc123",
            "cost_msats": 1000,
            "job_id": "mock-job",
        }
        
        with patch('cyberspace_cli.cloud_orchestration.run_cloud_compute', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            
            result = await compute_axis_in_cloud(
                axis='x',
                coord1=1000,
                coord2=2000,
                lca_height=20,
                privkey_hex="aa" * 32,
                pubkey_hex="bb" * 32,
                max_compute_height=16,
            )
            
            assert result.axis == 'x'
            assert result.axis_root == 0xabc123
            assert result.lca_height == 20
            assert result.job_id == "mock-job"
            assert result.cost_sats == 1  # 1000 msats = 1 sat
            
            # Verify run_cloud_compute was called with correct params
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["job_type"] == "hop"
            assert call_kwargs["params"]["axis"] == "x"
            assert call_kwargs["params"]["height"] == 20
    
    @pytest.mark.asyncio
    async def test_compute_y_axis(self):
        """Compute Y axis in cloud."""
        mock_result = {
            "axis_root_hex": "0xdef456",
            "cost_msats": 2000,
        }
        
        with patch('cyberspace_cli.cloud_orchestration.run_cloud_compute', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            
            result = await compute_axis_in_cloud(
                axis='y',
                coord1=5000,
                coord2=10000,
                lca_height=22,
                privkey_hex="cc" * 32,
                pubkey_hex="dd" * 32,
                max_compute_height=16,
            )
            
            assert result.axis == 'y'
            assert result.axis_root == 0xdef456
    
    @pytest.mark.asyncio
    async def test_integer_axis_root(self):
        """Handle integer axis_root_hex from cloud."""
        mock_result = {
            "axis_root_hex": 1234567890,
            "cost_msats": 0,
        }
        
        with patch('cyberspace_cli.cloud_orchestration.run_cloud_compute', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            
            result = await compute_axis_in_cloud(
                axis='z',
                coord1=0,
                coord2=1000,
                lca_height=18,
                privkey_hex="ee" * 32,
                pubkey_hex="ff" * 32,
                max_compute_height=16,
            )
            
            assert result.axis_root == 1234567890


class TestComputeSpatialRootsHybrid:
    """Test hybrid local/cloud spatial root computation."""
    
    @pytest.mark.asyncio
    async def test_all_local_compute(self):
        """All axes computed locally when within capacity."""
        with patch('cyberspace_cli.cloud_orchestration.run_cloud_compute') as mock_run:
            cantor_x, cantor_y, cantor_z, metadata = await compute_spatial_roots_hybrid(
                x1=0, y1=0, z1=0,
                x2=100, y2=200, z2=300,
                max_compute_height=16,
                privkey_hex="11" * 32,
                pubkey_hex="22" * 32,
            )
            
            # Cloud should not be called
            mock_run.assert_not_called()
            
            # Metadata should indicate no cloud
            assert metadata["cloud_axis"] is None
            assert metadata["cloud_result"] is None
            assert isinstance(metadata["lca_heights"], tuple)
            assert len(metadata["lca_heights"]) == 3
    
    @pytest.mark.asyncio
    async def test_x_axis_cloud_compute(self):
        """X axis computed in cloud when it exceeds capacity."""
        mock_result = {
            "axis_root_hex": "0xdeadbeef",
            "cost_msats": 1000,
        }
        
        with patch('cyberspace_cli.cloud_orchestration.run_cloud_compute', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            
            # Create coordinates where X has high LCA height
            # x1=0, x2=2^20 will have LCA height ~20
            x2 = (1 << 20) - 1
            
            cantor_x, cantor_y, cantor_z, metadata = await compute_spatial_roots_hybrid(
                x1=0, y1=0, z1=0,
                x2=x2, y2=100, z2=200,
                max_compute_height=16,
                privkey_hex="33" * 32,
                pubkey_hex="44" * 32,
            )
            
            # Cloud should be called
            assert mock_run.called
            assert metadata["cloud_axis"] == 'x'
            assert metadata["cloud_result"] is not None
            assert metadata["cloud_result"].axis == 'x'
            assert cantor_x == 0xdeadbeef
